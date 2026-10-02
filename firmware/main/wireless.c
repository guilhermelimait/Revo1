/* Wireless link to the Revo1 app: Wi-Fi (TCP) and Bluetooth LE (GATT), both
   carrying the same end-to-end encrypted session. See revo1/secure.py for the
   other side; the two must stay in step.

   Pairing happens over USB only (PAIR in main.c), which gives both sides a
   32-byte key. A session then runs a mutual challenge-response:

       app  -> knob   "R1H1" + app nonce (16)
       knob -> app    knob nonce (16) + HMAC-SHA256(key, "revo1-knob" | nonces)
       app  -> knob   HMAC-SHA256(key, "revo1-app" | nonces)

   and derives one AES-256-GCM key per direction from the key and both nonces.
   Frames are a 2-byte big-endian length (ciphertext + tag), then the
   ciphertext and a 16-byte tag; the nonce is a per-direction counter and the
   length is the associated data. Inside are ordinary protocol lines. */

#include "wireless.h"

#include <stdio.h>
#include <string.h>

#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/message_buffer.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "lwip/sockets.h"
#include "mbedtls/gcm.h"
#include "mbedtls/md.h"
#include "mbedtls/sha256.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "nvs.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

#define LINK_NAMESPACE "link"
#define NONCE_BYTES 16
#define MAC_BYTES 32
#define GCM_TAG_BYTES 16
#define FRAME_MAX 8192
#define LINE_BYTES 4200
#define TCP_PORT 47010
#define DISCOVERY_PORT 47011
#define HANDSHAKE_US 10000000
#define BLE_STREAM_BYTES (24 * 1024)

enum { LINK_WIFI = 1, LINK_BLE = 2 };
enum { WIFI_OFF, WIFI_CONNECTING, WIFI_CONNECTED, WIFI_BAD_PASSWORD, WIFI_NOT_FOUND };

typedef struct session session_t;
struct session {
    int kind;
    bool (*send_raw)(const uint8_t *data, size_t length);
    SemaphoreHandle_t lock;
    volatile bool open;
    volatile bool failed;
    int stage;
    int64_t started_us;
    uint8_t client_nonce[NONCE_BYTES];
    uint8_t knob_nonce[NONCE_BYTES];
    mbedtls_gcm_context rx;
    mbedtls_gcm_context tx;
    bool keys_ready;
    uint64_t rx_count;
    uint64_t tx_count;
    uint8_t *in;
    size_t have;
    uint8_t *plain;
    uint8_t *out;
    char *line;
    size_t line_length;
    bool overflow;
};

static wireless_line_fn line_handler;
static uint8_t link_key[WIRELESS_KEY_BYTES];
static volatile bool paired;
static char key_id[9] = "-";
static char wifi_ssid[33];
static char wifi_password[65];
static char device_name[16];

static session_t tcp_session;
static session_t ble_session;

/* ----- Crypto ------------------------------------------------------------ */

static void hmac_nonces(const char *label, const uint8_t *client, const uint8_t *knob,
                        uint8_t out[MAC_BYTES])
{
    uint8_t message[16 + 2 * NONCE_BYTES];
    const size_t label_length = strlen(label);
    memcpy(message, label, label_length);
    memcpy(message + label_length, client, NONCE_BYTES);
    memcpy(message + label_length + NONCE_BYTES, knob, NONCE_BYTES);
    mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), link_key,
                    sizeof(link_key), message, label_length + 2 * NONCE_BYTES, out);
}

static bool same_bytes(const uint8_t *a, const uint8_t *b, size_t length)
{
    uint8_t difference = 0;
    for (size_t index = 0; index < length; ++index) difference |= a[index] ^ b[index];
    return difference == 0;
}

static void frame_nonce(uint64_t counter, uint8_t nonce[12])
{
    memset(nonce, 0, 4);
    for (int index = 0; index < 8; ++index) nonce[4 + index] = (uint8_t)(counter >> (56 - 8 * index));
}

/* ----- Sessions ---------------------------------------------------------- */

static bool session_setup(session_t *session, int kind,
                          bool (*send_raw)(const uint8_t *, size_t))
{
    session->kind = kind;
    session->send_raw = send_raw;
    session->lock = xSemaphoreCreateMutex();
    session->in = heap_caps_malloc(FRAME_MAX + 2, MALLOC_CAP_SPIRAM);
    session->plain = heap_caps_malloc(FRAME_MAX, MALLOC_CAP_SPIRAM);
    session->out = heap_caps_malloc(FRAME_MAX + 2, MALLOC_CAP_SPIRAM);
    session->line = heap_caps_malloc(LINE_BYTES, MALLOC_CAP_SPIRAM);
    return session->lock && session->in && session->plain && session->out && session->line;
}

static void session_reset(session_t *session)
{
    xSemaphoreTake(session->lock, portMAX_DELAY);
    session->open = false;
    session->failed = false;
    session->stage = 0;
    session->started_us = esp_timer_get_time();
    session->have = 0;
    session->line_length = 0;
    session->overflow = false;
    session->rx_count = session->tx_count = 0;
    if (session->keys_ready) {
        mbedtls_gcm_free(&session->rx);
        mbedtls_gcm_free(&session->tx);
        session->keys_ready = false;
    }
    xSemaphoreGive(session->lock);
}

/* Seals and sends `length` bytes; the caller holds the lock. */
static bool session_seal(session_t *session, const uint8_t *data, size_t length)
{
    while (length) {
        const size_t piece = length < FRAME_MAX - GCM_TAG_BYTES ? length : FRAME_MAX - GCM_TAG_BYTES;
        const size_t sealed = piece + GCM_TAG_BYTES;
        uint8_t nonce[12];
        frame_nonce(session->tx_count++, nonce);
        session->out[0] = (uint8_t)(sealed >> 8);
        session->out[1] = (uint8_t)sealed;
        if (mbedtls_gcm_crypt_and_tag(&session->tx, MBEDTLS_GCM_ENCRYPT, piece, nonce,
                                      sizeof(nonce), session->out, 2, data,
                                      session->out + 2, GCM_TAG_BYTES,
                                      session->out + 2 + piece) != 0 ||
            !session->send_raw(session->out, 2 + sealed)) {
            return false;
        }
        data += piece;
        length -= piece;
    }
    return true;
}

static void session_lines(session_t *session, const uint8_t *data, size_t length)
{
    for (size_t index = 0; index < length; ++index) {
        const char character = (char)data[index];
        if (character == '\n' || character == '\r') {
            if (session->line_length && !session->overflow) {
                session->line[session->line_length] = '\0';
                line_handler(session->line, session->line_length);
            }
            session->line_length = 0;
            session->overflow = false;
        } else if (session->line_length < LINE_BYTES - 1) {
            session->line[session->line_length++] = character;
        } else {
            session->overflow = true;
        }
    }
}

/* Handles one complete handshake message or frame in `session->in`. */
static bool session_step(session_t *session)
{
    if (session->stage == 0) {
        if (!paired || memcmp(session->in, "R1H1", 4) != 0) return false;
        memcpy(session->client_nonce, session->in + 4, NONCE_BYTES);
        esp_fill_random(session->knob_nonce, NONCE_BYTES);
        uint8_t reply[NONCE_BYTES + MAC_BYTES];
        memcpy(reply, session->knob_nonce, NONCE_BYTES);
        hmac_nonces("revo1-knob", session->client_nonce, session->knob_nonce,
                    reply + NONCE_BYTES);
        xSemaphoreTake(session->lock, portMAX_DELAY);
        const bool sent = session->send_raw(reply, sizeof(reply));
        xSemaphoreGive(session->lock);
        session->stage = 1;
        return sent;
    }
    if (session->stage == 1) {
        uint8_t expected[MAC_BYTES];
        hmac_nonces("revo1-app", session->client_nonce, session->knob_nonce, expected);
        if (!same_bytes(expected, session->in, MAC_BYTES)) return false;
        uint8_t key[MAC_BYTES];
        xSemaphoreTake(session->lock, portMAX_DELAY);
        mbedtls_gcm_init(&session->rx);
        mbedtls_gcm_init(&session->tx);
        session->keys_ready = true;
        hmac_nonces("revo1-c2k", session->client_nonce, session->knob_nonce, key);
        int result = mbedtls_gcm_setkey(&session->rx, MBEDTLS_CIPHER_ID_AES, key, 256);
        hmac_nonces("revo1-k2c", session->client_nonce, session->knob_nonce, key);
        result |= mbedtls_gcm_setkey(&session->tx, MBEDTLS_CIPHER_ID_AES, key, 256);
        memset(key, 0, sizeof(key));
        session->rx_count = session->tx_count = 0;
        session->stage = 2;
        session->open = result == 0;
        xSemaphoreGive(session->lock);
        return result == 0;
    }
    const size_t sealed = ((size_t)session->in[0] << 8) | session->in[1];
    const size_t length = sealed - GCM_TAG_BYTES;
    uint8_t nonce[12];
    frame_nonce(session->rx_count++, nonce);
    if (mbedtls_gcm_auth_decrypt(&session->rx, length, nonce, sizeof(nonce), session->in, 2,
                                 session->in + 2 + length, GCM_TAG_BYTES, session->in + 2,
                                 session->plain) != 0) {
        return false;
    }
    session_lines(session, session->plain, length);
    return true;
}

/* Feeds bytes from the transport; false means drop the connection. */
static bool session_feed(session_t *session, const uint8_t *data, size_t length)
{
    while (length) {
        size_t want;
        if (session->stage == 0) {
            want = 4 + NONCE_BYTES;
        } else if (session->stage == 1) {
            want = MAC_BYTES;
        } else if (session->have < 2) {
            want = 2;
        } else {
            want = 2 + (((size_t)session->in[0] << 8) | session->in[1]);
        }
        size_t take = want - session->have;
        if (take > length) take = length;
        memcpy(session->in + session->have, data, take);
        session->have += take;
        data += take;
        length -= take;
        if (session->have < want) continue;
        if (session->stage == 2 && want == 2) {
            const size_t sealed = ((size_t)session->in[0] << 8) | session->in[1];
            if (sealed < GCM_TAG_BYTES || sealed > FRAME_MAX) return false;
            continue;
        }
        if (!session_step(session)) return false;
        session->have = 0;
    }
    return true;
}

static bool session_stale(const session_t *session)
{
    return session->stage < 2 && esp_timer_get_time() - session->started_us > HANDSHAKE_US;
}

void wireless_send(const char *text, size_t length)
{
    session_t *sessions[] = {&tcp_session, &ble_session};
    for (int index = 0; index < 2; ++index) {
        session_t *session = sessions[index];
        if (!session->lock || !session->open) continue;
        xSemaphoreTake(session->lock, portMAX_DELAY);
        if (session->open && !session_seal(session, (const uint8_t *)text, length)) {
            session->open = false;
            session->failed = true;
        }
        xSemaphoreGive(session->lock);
    }
}

/* ----- Wi-Fi ------------------------------------------------------------- */

static bool wifi_ready;
static volatile bool wifi_wanted;
static volatile int wifi_state = WIFI_OFF;
static volatile uint32_t wifi_ip;
static esp_netif_t *wifi_netif;
static esp_timer_handle_t wifi_retry;
static volatile int tcp_client = -1;

static void wifi_event(void *argument, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        if (wifi_wanted) {
            wifi_state = WIFI_CONNECTING;
            esp_wifi_connect();
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        wifi_ip = 0;
        if (!wifi_wanted) {
            wifi_state = WIFI_OFF;
            return;
        }
        switch (event->reason) {
        case WIFI_REASON_AUTH_FAIL:
        case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
        case WIFI_REASON_HANDSHAKE_TIMEOUT:
            wifi_state = WIFI_BAD_PASSWORD;
            break;
        case WIFI_REASON_NO_AP_FOUND:
            wifi_state = WIFI_NOT_FOUND;
            break;
        default:
            if (wifi_state == WIFI_CONNECTED) wifi_state = WIFI_CONNECTING;
            break;
        }
        esp_timer_stop(wifi_retry);
        esp_timer_start_once(wifi_retry, 3000000);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        wifi_ip = event->ip_info.ip.addr;
        wifi_state = WIFI_CONNECTED;
    }
}

static void wifi_reconnect(void *argument)
{
    if (wifi_wanted) esp_wifi_connect();
}

static bool tcp_send(const uint8_t *data, size_t length)
{
    const int client = tcp_client;
    while (length && client >= 0) {
        const int sent = send(client, data, length, 0);
        if (sent <= 0) return false;
        data += sent;
        length -= (size_t)sent;
    }
    return length == 0;
}

static void tcp_close(void)
{
    xSemaphoreTake(tcp_session.lock, portMAX_DELAY);
    tcp_session.open = false;
    if (tcp_client >= 0) {
        shutdown(tcp_client, SHUT_RDWR);
        close(tcp_client);
        tcp_client = -1;
    }
    xSemaphoreGive(tcp_session.lock);
}

static void tcp_task(void *argument)
{
    const int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    const int on = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
    struct sockaddr_in address = {
        .sin_family = AF_INET,
        .sin_port = htons(TCP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 ||
        listen(listener, 1) != 0) {
        close(listener);
        vTaskDelete(NULL);
        return;
    }
    static uint8_t buffer[1460];
    for (;;) {
        fd_set ready;
        FD_ZERO(&ready);
        FD_SET(listener, &ready);
        int highest = listener;
        const int client = tcp_client;
        if (client >= 0) {
            FD_SET(client, &ready);
            if (client > highest) highest = client;
        }
        struct timeval wait = {.tv_sec = 1};
        const int count = select(highest + 1, &ready, NULL, NULL, &wait);
        if (client >= 0 && (tcp_session.failed || session_stale(&tcp_session) || !paired)) {
            tcp_close();
            continue;
        }
        if (count <= 0) continue;
        if (FD_ISSET(listener, &ready)) {
            const int incoming = accept(listener, NULL, NULL);
            if (incoming >= 0) {
                /* The newest connection wins: the app reconnecting after a
                   network change must not wait for the old socket to die. */
                if (tcp_client >= 0) tcp_close();
                const int idle = 5, interval = 2, probes = 3;
                const struct timeval send_limit = {.tv_sec = 3};
                setsockopt(incoming, IPPROTO_TCP, TCP_NODELAY, &on, sizeof(on));
                setsockopt(incoming, SOL_SOCKET, SO_KEEPALIVE, &on, sizeof(on));
                setsockopt(incoming, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
                setsockopt(incoming, IPPROTO_TCP, TCP_KEEPINTVL, &interval, sizeof(interval));
                setsockopt(incoming, IPPROTO_TCP, TCP_KEEPCNT, &probes, sizeof(probes));
                setsockopt(incoming, SOL_SOCKET, SO_SNDTIMEO, &send_limit, sizeof(send_limit));
                session_reset(&tcp_session);
                tcp_client = incoming;
            }
            continue;
        }
        if (client >= 0 && FD_ISSET(client, &ready)) {
            const int received = recv(client, buffer, sizeof(buffer), 0);
            if (received <= 0 || !session_feed(&tcp_session, buffer, (size_t)received)) {
                tcp_close();
            }
        }
    }
}

/* Answers "REVO1?" broadcasts so the app can find the knob on the network. */
static void discovery_task(void *argument)
{
    const int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    struct sockaddr_in address = {
        .sin_family = AF_INET,
        .sin_port = htons(DISCOVERY_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (struct sockaddr *)&address, sizeof(address)) != 0) {
        close(sock);
        vTaskDelete(NULL);
        return;
    }
    char request[16];
    char reply[48];
    for (;;) {
        struct sockaddr_in sender;
        socklen_t sender_length = sizeof(sender);
        const int received = recvfrom(sock, request, sizeof(request) - 1, 0,
                                      (struct sockaddr *)&sender, &sender_length);
        if (received != 6 || memcmp(request, "REVO1?", 6) != 0 || !paired) continue;
        const int length = snprintf(reply, sizeof(reply), "REVO1,%s,%s", key_id, device_name);
        sendto(sock, reply, length, 0, (struct sockaddr *)&sender, sender_length);
    }
}

static void wifi_apply(void)
{
    wifi_wanted = paired && wifi_ssid[0];
    if (!wifi_ready) {
        if (!wifi_wanted) return;
        esp_netif_init();
        esp_event_loop_create_default();
        wifi_netif = esp_netif_create_default_wifi_sta();
        char host[20];
        snprintf(host, sizeof(host), "%s", device_name);
        for (char *c = host; *c; ++c) {
            if (*c >= 'A' && *c <= 'Z') *c = (char)(*c - 'A' + 'a');
        }
        esp_netif_set_hostname(wifi_netif, host);
        wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
        if (esp_wifi_init(&config) != ESP_OK) return;
        esp_wifi_set_storage(WIFI_STORAGE_RAM);
        esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL, NULL);
        esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL, NULL);
        const esp_timer_create_args_t retry = {.callback = wifi_reconnect, .name = "wifi_retry"};
        esp_timer_create(&retry, &wifi_retry);
        esp_wifi_set_mode(WIFI_MODE_STA);
        xTaskCreate(tcp_task, "link_tcp", 4096, NULL, 3, NULL);
        xTaskCreate(discovery_task, "link_find", 3072, NULL, 2, NULL);
        wifi_ready = true;
    }
    esp_wifi_disconnect();
    esp_wifi_stop();
    wifi_ip = 0;
    wifi_state = WIFI_OFF;
    if (!wifi_wanted) return;
    wifi_config_t config = {0};
    memcpy(config.sta.ssid, wifi_ssid, strlen(wifi_ssid));
    memcpy(config.sta.password, wifi_password, strlen(wifi_password));
    config.sta.threshold.authmode = wifi_password[0] ? WIFI_AUTH_WPA_WPA2_PSK : WIFI_AUTH_OPEN;
    config.sta.pmf_cfg.capable = true;
    config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;
    esp_wifi_set_config(WIFI_IF_STA, &config);
    wifi_state = WIFI_CONNECTING;
    esp_wifi_start();
}

/* ----- Bluetooth LE ------------------------------------------------------ */

/* 7b8f0001-6c1e-4e8a-9c3d-2a1f5e0b9a10, then ...0002 (app writes) and
   ...0003 (knob notifies). */
static const ble_uuid128_t service_uuid = BLE_UUID128_INIT(
    0x10, 0x9a, 0x0b, 0x5e, 0x1f, 0x2a, 0x3d, 0x9c, 0x8a, 0x4e, 0x1e, 0x6c, 0x01, 0x00, 0x8f, 0x7b);
static const ble_uuid128_t rx_uuid = BLE_UUID128_INIT(
    0x10, 0x9a, 0x0b, 0x5e, 0x1f, 0x2a, 0x3d, 0x9c, 0x8a, 0x4e, 0x1e, 0x6c, 0x02, 0x00, 0x8f, 0x7b);
static const ble_uuid128_t tx_uuid = BLE_UUID128_INIT(
    0x10, 0x9a, 0x0b, 0x5e, 0x1f, 0x2a, 0x3d, 0x9c, 0x8a, 0x4e, 0x1e, 0x6c, 0x03, 0x00, 0x8f, 0x7b);

static bool ble_started;
static volatile bool ble_synced;
static uint8_t ble_address_type;
static volatile uint16_t ble_connection = BLE_HS_CONN_HANDLE_NONE;
static uint16_t ble_tx_handle;
/* Each write is one message, tagged with the connection it arrived on, so
   bytes left from a dropped connection never reach the next handshake. */
static MessageBufferHandle_t ble_stream;
static volatile bool ble_overflow;
static volatile bool ble_drop;
static volatile uint8_t ble_generation;

static int ble_access(uint16_t connection, uint16_t attribute,
                      struct ble_gatt_access_ctxt *context, void *argument)
{
    static uint8_t buffer[1 + 520];
    if (context->op != BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t length = 0;
    if (OS_MBUF_PKTLEN(context->om) > sizeof(buffer) - 1 ||
        ble_hs_mbuf_to_flat(context->om, buffer + 1, sizeof(buffer) - 1, &length) != 0) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    if (length == 0) return 0;
    buffer[0] = ble_generation;
    if (xMessageBufferSend(ble_stream, buffer, length + 1u, 0) != length + 1u) {
        ble_overflow = true;
    }
    return 0;
}

static const struct ble_gatt_svc_def ble_services[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &service_uuid.u,
        .characteristics = (struct ble_gatt_chr_def[]){
            {
                .uuid = &rx_uuid.u,
                .access_cb = ble_access,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
            },
            {
                .uuid = &tx_uuid.u,
                .access_cb = ble_access,
                .flags = BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &ble_tx_handle,
            },
            {0},
        },
    },
    {0},
};

static int ble_gap_event(struct ble_gap_event *event, void *argument);

static void ble_advertise(void)
{
    if (!ble_synced || !paired || ble_connection != BLE_HS_CONN_HANDLE_NONE ||
        ble_gap_adv_active()) {
        return;
    }
    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = &service_uuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    ble_gap_adv_set_fields(&fields);
    struct ble_hs_adv_fields response = {0};
    response.name = (const uint8_t *)device_name;
    response.name_len = strlen(device_name);
    response.name_is_complete = 1;
    ble_gap_adv_rsp_set_fields(&response);
    struct ble_gap_adv_params parameters = {
        .conn_mode = BLE_GAP_CONN_MODE_UND,
        .disc_mode = BLE_GAP_DISC_MODE_GEN,
        .itvl_min = 160,
        .itvl_max = 240,
    };
    ble_gap_adv_start(ble_address_type, NULL, BLE_HS_FOREVER, &parameters, ble_gap_event, NULL);
}

static int ble_gap_event(struct ble_gap_event *event, void *argument)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            ble_generation++;
            ble_drop = true;
            ble_connection = event->connect.conn_handle;
            /* Ask for a short interval: uploads ride on it. */
            const struct ble_gap_upd_params fast = {
                .itvl_min = 6, .itvl_max = 12, .latency = 0,
                .supervision_timeout = 400,
            };
            ble_gap_update_params(event->connect.conn_handle, &fast);
        } else {
            ble_advertise();
        }
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        ble_connection = BLE_HS_CONN_HANDLE_NONE;
        ble_session.open = false;
        ble_generation++;
        ble_drop = true;
        ble_advertise();
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        ble_advertise();
        break;
    default:
        break;
    }
    return 0;
}

static void ble_on_sync(void)
{
    ble_hs_util_ensure_addr(0);
    ble_hs_id_infer_auto(0, &ble_address_type);
    ble_synced = true;
    ble_advertise();
}

static void ble_host_task(void *argument)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static bool ble_send(const uint8_t *data, size_t length)
{
    const uint16_t connection = ble_connection;
    if (connection == BLE_HS_CONN_HANDLE_NONE) return false;
    const size_t piece_max = ble_att_mtu(connection) > 3 ? ble_att_mtu(connection) - 3 : 20;
    while (length) {
        const size_t piece = length < piece_max ? length : piece_max;
        int attempts = 0;
        for (;;) {
            struct os_mbuf *message = ble_hs_mbuf_from_flat(data, piece);
            const int result = message
                ? ble_gatts_notify_custom(connection, ble_tx_handle, message)
                : BLE_HS_ENOMEM;
            if (result == 0) break;
            if (result != BLE_HS_ENOMEM || ++attempts > 200) return false;
            vTaskDelay(pdMS_TO_TICKS(5));
        }
        data += piece;
        length -= piece;
    }
    return true;
}

static void ble_terminate(void)
{
    const uint16_t connection = ble_connection;
    if (connection != BLE_HS_CONN_HANDLE_NONE) {
        ble_gap_terminate(connection, BLE_ERR_REM_USER_CONN_TERM);
    }
}

static void ble_worker_task(void *argument)
{
    static uint8_t buffer[1 + 520];
    uint8_t generation = ble_generation;
    for (;;) {
        size_t received = xMessageBufferReceive(ble_stream, buffer, sizeof(buffer),
                                                pdMS_TO_TICKS(200));
        if (ble_drop) {
            /* A new or closed connection: start the handshake afresh. */
            ble_drop = false;
            ble_overflow = false;
            generation = ble_generation;
            session_reset(&ble_session);
        }
        /* Writes from an earlier connection are dropped. */
        if (received && buffer[0] != generation) received = 0;
        if (ble_connection == BLE_HS_CONN_HANDLE_NONE) continue;
        if (ble_overflow || ble_session.failed || session_stale(&ble_session) ||
            (received && !session_feed(&ble_session, buffer + 1, received - 1))) {
            ble_session.open = false;
            ble_overflow = false;
            ble_terminate();
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
}

static void ble_start(void)
{
    if (ble_started) {
        ble_advertise();
        return;
    }
    ble_stream = xMessageBufferCreateWithCaps(BLE_STREAM_BYTES, MALLOC_CAP_SPIRAM);
    if (!ble_stream || nimble_port_init() != ESP_OK) return;
    ble_hs_cfg.sync_cb = ble_on_sync;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    if (ble_gatts_count_cfg(ble_services) != 0 || ble_gatts_add_svcs(ble_services) != 0) return;
    ble_svc_gap_device_name_set(device_name);
    xTaskCreate(ble_worker_task, "link_ble", 4096, NULL, 3, NULL);
    nimble_port_freertos_init(ble_host_task);
    ble_started = true;
}

static void ble_stop(void)
{
    if (!ble_started) return;
    if (ble_synced) ble_gap_adv_stop();
    ble_terminate();
}

/* ----- Pairing ----------------------------------------------------------- */

static void update_key_id(void)
{
    if (!paired) {
        strcpy(key_id, "-");
        return;
    }
    uint8_t digest[32];
    mbedtls_sha256(link_key, sizeof(link_key), digest, 0);
    snprintf(key_id, sizeof(key_id), "%02X%02X%02X%02X", digest[0], digest[1], digest[2],
             digest[3]);
}

static void drop_sessions(void)
{
    tcp_session.open = false;
    tcp_session.failed = true;
    ble_session.open = false;
    ble_terminate();
}

void wireless_init(wireless_line_fn on_line)
{
    line_handler = on_line;
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(device_name, sizeof(device_name), "Revo1-%02X%02X", mac[4], mac[5]);
    if (!session_setup(&tcp_session, LINK_WIFI, tcp_send) ||
        !session_setup(&ble_session, LINK_BLE, ble_send)) {
        return;
    }
    nvs_handle_t handle;
    if (nvs_open(LINK_NAMESPACE, NVS_READONLY, &handle) == ESP_OK) {
        size_t length = sizeof(link_key);
        paired = nvs_get_blob(handle, "key", link_key, &length) == ESP_OK &&
                 length == sizeof(link_key);
        length = sizeof(wifi_ssid);
        if (nvs_get_str(handle, "ssid", wifi_ssid, &length) != ESP_OK) wifi_ssid[0] = '\0';
        length = sizeof(wifi_password);
        if (nvs_get_str(handle, "pass", wifi_password, &length) != ESP_OK) wifi_password[0] = '\0';
        nvs_close(handle);
    }
    update_key_id();
    if (!paired) return;
    ble_start();
    wifi_apply();
}

bool wireless_pair(const uint8_t key[WIRELESS_KEY_BYTES], const char *ssid,
                   const char *password)
{
    if (strlen(ssid) >= sizeof(wifi_ssid) || strlen(password) >= sizeof(wifi_password) ||
        !tcp_session.lock) {
        return false;
    }
    nvs_handle_t handle;
    if (nvs_open(LINK_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return false;
    const bool stored = nvs_set_blob(handle, "key", key, WIRELESS_KEY_BYTES) == ESP_OK &&
                        nvs_set_str(handle, "ssid", ssid) == ESP_OK &&
                        nvs_set_str(handle, "pass", password) == ESP_OK &&
                        nvs_commit(handle) == ESP_OK;
    nvs_close(handle);
    if (!stored) return false;
    drop_sessions();
    memcpy(link_key, key, WIRELESS_KEY_BYTES);
    strcpy(wifi_ssid, ssid);
    strcpy(wifi_password, password);
    paired = true;
    update_key_id();
    ble_start();
    wifi_apply();
    return true;
}

void wireless_unpair(void)
{
    nvs_handle_t handle;
    if (nvs_open(LINK_NAMESPACE, NVS_READWRITE, &handle) == ESP_OK) {
        nvs_erase_all(handle);
        nvs_commit(handle);
        nvs_close(handle);
    }
    paired = false;
    drop_sessions();
    memset(link_key, 0, sizeof(link_key));
    wifi_ssid[0] = wifi_password[0] = '\0';
    update_key_id();
    ble_stop();
    wifi_apply();
}

void wireless_status(char *out, size_t size)
{
    char address[16] = "-";
    const uint32_t ip = wifi_ip;
    if (ip) {
        snprintf(address, sizeof(address), "%u.%u.%u.%u", (unsigned)(ip & 0xFF),
                 (unsigned)((ip >> 8) & 0xFF), (unsigned)((ip >> 16) & 0xFF),
                 (unsigned)(ip >> 24));
    }
    const int links = (tcp_session.open ? 1 : 0) | (ble_session.open ? 2 : 0);
    snprintf(out, size, "NET,%s,%d,%s,%s,%d", key_id, wifi_state, address, device_name, links);
}
