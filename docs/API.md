# 📡 Murnet API v5.0

Murnet предоставляет HTTP REST API и WebSocket для интеграции с внешними приложениями.

## 🔐 Аутентификация

API защищено JWT-токенами. Чтобы получить доступ к эндпоинтам, необходимо сначала получить токен через `/auth/login`, а затем передавать его в заголовке `Authorization: Bearer <token>`.

## 📍 Базовый URL

По умолчанию API доступно по адресу `http://127.0.0.1:8080`. В VDS-профиле хост меняется на `0.0.0.0`.

## 📋 Модели данных

Основные модели данных описаны в `api/models.py` и используют Pydantic. Вот некоторые из них:

*   **`MessageInfo`**: Информация о сообщении (`id`, `from`, `to`, `content_preview`, `timestamp`, `delivered`, `read`).
*   **`NodeInfo`**: Информация об узле (`address`, `public_key`, `status`, `peers_count`, `messages_count` и т.д.).
*   **`PeerInfo`**: Информация о подключенном пире (`address`, `ip`, `port`, `rtt`, `is_active`).

## 🚀 Основные Эндпоинты

### Аутентификация

#### `POST /auth/login`
Получить JWT-токен для дальнейшей работы.
*   **Ответ (200 OK):**
    ```json
    {
      "success": true,
      "token": "eyJhbGciOiJIUzI1NiIs...",
      "expires_at": 1712345678.0,
      "node_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    }
    ```

#### `POST /auth/logout`
Отозвать текущий JWT-токен.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ (200 OK):** `{"success": true}`

### Сообщения

#### `POST /messages/send`
Отправить сообщение.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Тело запроса (`SendMessageRequest`):**
    ```json
    {
      "to_address": "1RecipientAddress...",
      "content": "Привет, мир!",
      "message_type": "text",
      "encrypt": true
    }
    ```
*   **Ответ (200 OK):**
    ```json
    {
      "success": true,
      "message_id": "uuid-сообщения",
      "message": "Message queued"
    }
    ```

#### `GET /messages/inbox`
Получить входящие сообщения.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Параметры запроса:** `?limit=50&offset=0&unread_only=false`
*   **Ответ (200 OK):** Список объектов [`MessageInfo`].

### Файлы

#### `POST /files/upload`
Загрузить файл в сеть.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Метод:** `multipart/form-data`
*   **Поля:**
    *   `file`: Файл для загрузки.
    *   `to_address` (опц.): Адрес получателя. Если указан, файл будет ему отправлен как сообщение.
*   **Ответ (200 OK):**
    ```json
    {
      "success": true,
      "file_id": "generated-uuid-for-file",
      "filename": "original_name.txt",
      "size": 12345,
      "hash": "blake2b_hash_of_file"
    }
    ```

#### `GET /files/{file_id}`
Скачать файл по его ID.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ:** Потоковое скачивание файла.

### Сеть и Узел

#### `GET /network/status`
Получить полный статус узла.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ:** Объект [`FullStatusResponse`], содержащий детальную информацию об узле, сети, хранилище и DHT.

#### `GET /network/peers`
Получить список подключенных пиров.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ:** Список объектов [`PeerInfo`].

#### `POST /network/connect`
Инициировать подключение к новому пиру.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Тело запроса (`ConnectPeerRequest`):**
    ```json
    {
      "ip": "192.168.1.100",
      "port": 8888,
      "address": "1OptionalAddress..." // Если известен адрес пира
    }
    ```

### DHT и Хранилище

#### `GET /dht/stats`
Статистика по DHT.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ:** Объект [`DHTStats`].

#### `GET /storage/stats`
Статистика по хранилищу.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ:** Объект [`StorageStats`].

### Имена (Name System)

#### `POST /names/register`
Зарегистрировать имя для своего адреса (публикуется в DHT).
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Тело запроса (`RegisterNameRequest`):**
    ```json
    {
      "name": "alice.murnet",
      "public": true
    }
    ```

#### `GET /names/lookup/{name}`
Найти адрес по имени.
*   **Заголовки:** `Authorization: Bearer <token>`
*   **Ответ:**
    ```json
    {
      "success": true,
      "name": "alice.murnet",
      "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    }
    ```

### Системное

#### `GET /health`
Проверка здоровья узла.
*   **Ответ:**
    ```json
    {
      "status": "healthy",
      "node_running": true,
      "timestamp": 1712345678.0
    }
    ```

## 🔌 WebSocket API

Эндпоинт: `ws://127.0.0.1:8080/ws`

1.  **Аутентификация:** Клиент должен отправить JSON-сообщение сразу после подключения:
    ```json
    {
      "token": "your_jwt_token",
      "node_address": "your_node_address"
    }
    ```
2.  **Типы сообщений:**
    *   `ping` (клиент -> сервер): Проверка соединения.
    *   `pong` (сервер -> клиент): Ответ на ping.
    *   `status` (клиент -> сервер): Запрос текущего статуса узла.
    *   `message_new` (сервер -> клиент): Уведомление о новом сообщении.
    *   `peer_connected` / `peer_disconnected` (сервер -> клиент): Уведомления о пирах.
    *   `sync_start` / `sync_complete` (сервер -> клиент): События синхронизации.
```
