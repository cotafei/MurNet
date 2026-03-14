# 📡 Murnet Protocol Specification v5.1

Данный документ описывает сетевой протокол Murnet — децентрализованной P2P сети с усиленной безопасностью. Протокол разработан с учетом современных требований к приватности, отказоустойчивости и защите от различных классов атак.

## 📋 Обзор протокола

Murnet использует комбинацию нескольких протоколов:

1.  **Транспортный уровень:** UDP с подтверждением доставки (ACK) и защитой от реплей-атак
2.  **Маршрутизация:** Link-State протокол с подписанными LSA (Link State Advertisements)
3.  **Хранилище:** Распределенная хеш-таблица (DHT) на базе Kademlia
4.  **Криптография:** Ed25519, X25519, AES-256-GCM, Blake2b, Argon2id

## 🔢 Формат пакета

### Заголовок пакета (PacketHeader)

Все пакеты имеют фиксированный заголовок размером 38 байт:

```c
struct PacketHeader {
    uint8_t version;        // Версия протокола (v5 = 0x05)
    uint8_t packet_type;    // Тип пакета (см. PacketType)
    uint32_t sequence;      // Номер последовательности (anti-replay)
    uint32_t ack_sequence;  // Номер подтверждаемого пакета
    uint16_t payload_length; // Длина полезной нагрузки
    uint32_t timestamp;     // Временная метка (unix timestamp)
    uint32_t reserved;      // Зарезервировано (0)
    uint8_t auth_tag[16];   // HMAC-Blake2b тег аутентификации
};
```

### Типы пакетов (PacketType)

```python
PING = 0x01      # Проверка доступности
PONG = 0x02      # Ответ на ping
HELLO = 0x03     # Начало handshake
ACK = 0x04       # Подтверждение получения
DATA = 0x10      # Данные (сообщения)
DATA_FRAG = 0x11 # Фрагментированные данные
AUTH = 0x20      # Аутентификация
```

## 🔐 Криптографические примитивы

### Идентификация (Identity)

Каждый узел имеет криптографическую идентичность:

- **Алгоритм:** Ed25519
- **Приватный ключ:** 32 байта
- **Публичный ключ:** 32 байта
- **Адрес:** Base58(version(1) + Blake2b-160(pubkey) + checksum(4))

### Обмен ключами (X25519)

Для установления сессионных ключей используется X25519:

1.  Узел A генерирует эфемерную X25519 ключевую пару
2.  Отправляет публичный ключ узлу B в HELLO пакете
3.  Узел B вычисляет общий секрет: `shared = X25519(priv_B, pub_A)`
4.  Сессионный ключ: `HKDF(shared, salt=nonce, info="murnet_session_v5")`

### Аутентификация пакетов (HMAC)

Каждый пакет (кроме HELLO) аутентифицируется:

```
auth_tag = Blake2b(header_without_tag + payload, key=session_key, size=16)
```

### End-to-End шифрование сообщений

```
nonce = random(12)
ciphertext = AES-256-GCM(shared_secret, nonce, plaintext)
```

## 🤝 Handshake протокол

1.  **HELLO (Узел A -> Узел B):**
    ```json
    {
      "version": "5.1",
      "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
      "public_key": "a1b2c3...",
      "timestamp": 1712345678,
      "capabilities": ["auth", "encrypt", "compress"]
    }
    ```

2.  **HELLO (Узел B -> Узел A):**
    Аналогичный ответ с данными узла B

3.  **AUTH (Узел A -> Узел B) — опционально:**
    ```json
    {
      "type": "auth",
      "challenge": "random_nonce",
      "signature": "ed25519_signature"
    }
    ```

4.  **Установка сессионного ключа** (X25519)

## 📦 Формат сообщений

### Базовое сообщение

```json
{
  "type": "message",
  "id": "uuid-v4",
  "from": "1SenderAddress...",
  "to": "1RecipientAddress...",
  "text": "Привет, мир!",
  "timestamp": 1712345678.123,
  "ttl": 10,
  "path": ["1NodeA...", "1NodeB..."],
  "need_ack": true,
  "version": "v5-secure",
  "signature": "ed25519_signature_base64"
}
```

### Зашифрованное сообщение

```json
{
  "type": "message",
  "id": "uuid-v4",
  "from": "1SenderAddress...",
  "to": "1RecipientAddress...",
  "text": "[ENCRYPTED]",
  "encrypted": {
    "ciphertext": "base64_ciphertext",
    "nonce": "base64_nonce",
    "sender_pubkey": "base64_pubkey",
    "version": "v5"
  },
  "timestamp": 1712345678.123,
  "signature": "ed25519_signature_base64"
}
```

### Подтверждение (ACK)

```json
{
  "type": "ack",
  "ack_for": "uuid-сообщения",
  "from": "1NodeAddress...",
  "timestamp": 1712345678.223
}
```

## 🔄 DHT протокол (Kademlia)

### RPC вызовы

Все DHT RPC вызовы аутентифицируются HMAC:

```json
{
  "dht_type": "dht_store|dht_get|dht_rep|dht_hint|dht_ping|dht_sync",
  "dht_id": "uuid-request",
  "dht_key": "key_string",
  "dht_data": "hex_encoded_data",
  "dht_ttl": 3600,
  "dht_sender": "1NodeAddress...",
  "dht_timestamp": 1712345678,
  "dht_nonce": "unique_nonce_hex",
  "dht_signature": "hmac_signature_hex"
}
```

### Ответы

```json
{
  "dht_type": "dht_store_ack|dht_get_ack|...",
  "dht_request_id": "uuid-request",
  "dht_success": true,
  "dht_data": "hex_encoded_data",
  "dht_error": null,
  "dht_sender": "1NodeAddress...",
  "dht_signature": "hmac_signature_hex"
}
```

## 🛣️ Маршрутизация (Link-State)

### LSA (Link State Advertisement)

```json
{
  "origin": "1NodeAddress...",
  "sequence": 42,
  "links": {
    "1NeighborA...": {
      "cost": 1.0,
      "bandwidth": 1000.0,
      "latency": 10.0,
      "loss_rate": 0.01,
      "state": "up"
    },
    "1NeighborB...": {
      "cost": 2.0,
      "bandwidth": 500.0,
      "latency": 25.0,
      "loss_rate": 0.05,
      "state": "up"
    }
  },
  "timestamp": 1712345678,
  "ttl": 3600,
  "signature": "ed25519_signature_hex",
  "hash_chain": "prev_hash"
}
```

## 🔒 Защита от атак

### Replay-атаки

Каждый пакет содержит:
- **sequence:** Уникальный номер, отслеживаемый в скользящем окне (размер 1000)
- **timestamp:** Временная метка с допустимым отклонением ±300 секунд
- **nonce:** Для DHT RPC запросов

### Атаки Chalkias

При подписи данных используется ТОЛЬКО внутренний приватный ключ, публичный ключ не принимается извне.

### Флуд-атаки

- Rate limiting: 100 пакетов/сек с одного IP
- Глобальный лимит: 10000 пакетов/сек
- LSA flood detection: не более 10 LSA/сек с одного узла

### Бан-лист

При превышении лимита failed attempts (10+) узел временно блокируется.

## 📊 Примеры потоков данных

### Отправка сообщения с установленным соединением

```
[Клиент] -> [Узел A] -> [Узел B] -> [Узел C] -> [Получатель]
    |          |          |          |          |
    |--DATA--->|          |          |          |
    |          |--DATA--->|          |          |
    |          |          |--DATA--->|          |
    |          |          |          |--DATA--->|
    |          |          |          |<--ACK----|
    |          |          |<--ACK----|          |
    |          |<--ACK----|          |          |
    |<--ACK-----|          |          |          |
```

### Поиск ключа в DHT

```
[Запрос] -> [Узел A] -> [Узел B] -> [Узел C] (владелец)
    |          |          |          |
    |--GET---->|          |          |
    |          |--GET---->|          |
    |          |          |--GET---->|
    |          |          |<--DATA---|
    |          |<--DATA---|          |
    |<--DATA----|          |          |
```

## 🌐 Bootstrap узлы

Для первоначального подключения к сети используются публичные bootstrap узлы (список обновляется):

```
```

## 📈 Версионирование

Протокол использует семантическое версионирование:
- **MAJOR:** Несовместимые изменения протокола
- **MINOR:** Обратно совместимые расширения
- **PATCH:** Исправления безопасности

Текущая версия: **5.1**

## 🔬 Экспериментальные возможности

Версия 5.1 является экспериментальной и может содержать:

- Неоптимальные параметры rate limiting
- Возможные race conditions в многопоточности
- Неполное покрытие тестами edge cases
- Временные несовместимости между версиями

## 📚 Дополнительная информация

- Полная реализация: [core/transport.py](core/transport.py)
- Криптографические примитивы: [core/crypto.py](core/crypto.py)
- DHT реализация: [core/murnaked.py](core/murnaked.py)
- Маршрутизация: [core/routing.py](core/routing.py)
```

Этот файл описывает все ключевые аспекты протокола Murnet и может быть использован как справочник для разработчиков, желающих реализовать свою совместимую реализацию или просто понять, как работает сеть.