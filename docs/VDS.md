# ☁️ VDS и Продакшен

Это руководство описывает, как развернуть узел Murnet на виртуальном выделенном сервере (VDS) для обеспечения круглосуточной работы.

## 🐳 Развертывание с Docker

Самый простой и рекомендуемый способ.

### Подготовка

1.  Скопируйте папку `murnet` на ваш VDS.
2.  Перейдите в папку проекта: `cd murnet`

### Сборка и запуск

1.  **Сгенерируйте Docker-конфиги (если их нет):**
    ```bash
    python -c "from vds.docker import DockerGenerator; DockerGenerator.generate_all()"
    ```
    Это создаст `Dockerfile`, `docker-compose.yml` и папку `monitoring`.

2.  **Запустите контейнер:**
    ```bash
    # Запуск только узла
    docker-compose up -d

    # Запуск узла со стеком мониторинга (Prometheus + Grafana)
    docker-compose --profile monitoring up -d
    ```

3.  **Просмотр логов:**
    ```bash
    docker-compose logs -f murnet
    ```

## 🚀 Развертывание с systemd

Для более глубокой интеграции с операционной системой.

### Автоматическая установка

В комплекте идет скрипт для автоматической установки и настройки.

```bash
# Сгенерируйте systemd-файлы
python -c "from vds.systemd import SystemdManager; SystemdManager.generate_all()"

# Запустите установку (потребуются права sudo)
sudo ./install.sh
```

### Что делает скрипт `install.sh`?

1.  Создает пользователя `murnet`.
2.  Создает необходимые директории (`/opt/murnet`, `/var/lib/murnet`, `/var/log/murnet`).
3.  Устанавливает Python-зависимости в виртуальное окружение.
4.  Копирует systemd-сервисы (`murnet.service`, `murnet-maintenance.service`, `murnet-maintenance.timer`).
5.  Настраивает logrotate для ротации логов.
6.  Генерирует базовый конфиг в `/etc/murnet/config.yaml`.
7.  Добавляет правила для фаервола (UFW).
8.  Включает и запускает сервисы.

**Управление сервисом:**
```bash
sudo systemctl status murnet
sudo journalctl -u murnet -f
```

## 📊 Мониторинг (Prometheus + Grafana)

При использовании Docker с профилем `monitoring` или при самостоятельной настройке, Murnet предоставляет метрики в формате Prometheus на порту `9090`.

**Доступные метрики:**
*   `murnet_messages_sent_total` (counter)
*   `murnet_messages_received_total` (counter)
*   `murnet_peers_connected` (gauge)
*   `murnet_dht_entries` (gauge)
*   `murnet_storage_size_bytes` (gauge)
*   `murnet_message_latency_seconds` (histogram)
*   `murnet_bandwidth_bytes` (gauge, с метками `direction="in"|"out"`)

**Grafana:** Вы можете импортировать дашборд для визуализации этих метрик.

## 🔒 Безопасность VDS

1.  **Firewall:** Убедитесь, что открыты только необходимые порты: `8888/udp` (P2P), `8080/tcp` (API, если нужен извне), `9090/tcp` (метрики, если нужны). Используйте `ufw` или `iptables`.
    ```bash
    sudo ufw allow 8888/udp
    sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp # Разрешить API только из локальной сети
    ```
2.  **Reverse Proxy для API:** Если API должен быть доступен из интернета, настоятельно рекомендуется разместить его за reverse proxy (например, Nginx) с настроенным SSL (HTTPS).
3.  **Регулярные обновления:** Не забывайте обновлять систему и сам Murnet.
    ```bash
    git pull
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d
    ```
