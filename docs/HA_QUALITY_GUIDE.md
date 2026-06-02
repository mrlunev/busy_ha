# How to be integrated into Home Assistant (and not screw up)

> Переваренная выжимка из официальной доки HA (developers.home-assistant.io) под наш проект.
> Это **референс**, на который ссылаются жёсткие гейты в `.cursor/rules/`. Здесь — «почему» и «как»;
> в правилах — «что обязательно». Обновлять при изменении доки HA.
>
> Источники: Integration Quality Scale (overview + checklist + per-rule pages), Development checklist.
> Последняя сверка: 2026-06-02.

## 0. Стратегия дистрибуции (контекст)

**HACS-first → core-later.** Сейчас итерируем в HACS (тир `📦 Custom` — не ревьюится HA). Цель — попасть в `home-assistant/core` (папка `homeassistant/components/<domain>`) через PR, который проходит ревью и тянет **минимум 🥉 Bronze** (для новых интеграций это обязательный минимум). Поэтому **пишем код сразу по core-стандартам**, чтобы переезд был «процессом», а не переписыванием.

Путь в core ≠ регистрация/оплата. Это OSS-PR в `home-assistant/core` + отдельный PR ассетов в `home-assistant/brands`. «Сертификация» = Quality Scale. Вендорский бейдж «Works with Home Assistant» — надстройка поверх core (требует ≥ Gold).

## 1. Тиры качества (что значат)

| Тир | Смысл | Для нас |
|---|---|---|
| 🥉 Bronze | базовый минимум; UI-setup, базовые стандарты кода, тест на config flow | **обязательный порог для core** |
| 🥈 Silver | устойчивость: reconnect, reauth, unavailable, code owner | **наша реальная цель к сабмиту** |
| 🥇 Gold | discovery, переводы, диагностика, OTA, полное покрытие тестами | требуется для «Works with HA» |
| 🏆 Platinum | полностью async, строгая типизация, эффективный I/O | долгосрок |

Прогресс трекается файлом `quality_scale.yaml` в интеграции (`rules: { config_flow: done, <rule>: { status: exempt, comment: ... } }`).

## 2. Hard idioms — «не облажаться» (с кодом)

Это правила, которые агенты чаще всего нарушают. Все — Bronze/Silver, т.е. блокеры для core.

### 2.1 `runtime-data` (Bronze) — НЕ `hass.data`
Хранить рантайм в `entry.runtime_data`, типизировано. Не `hass.data[DOMAIN][entry_id]`.
```python
type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]

async def async_setup_entry(hass, entry: BusyBarConfigEntry) -> bool:
    coordinator = BusyBarCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator            # ← так
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```
Платформы и сервисы достают через `entry.runtime_data`, не из `hass.data`.

### 2.2 `test-before-setup` (Bronze) — правильные исключения при старте
```python
try:
    await coordinator.async_config_entry_first_refresh()  # implicit-вариант — ок
except OfflineError as ex:
    raise ConfigEntryNotReady("Device offline") from ex   # временно → HA повторит
except InvalidAuthError as ex:
    raise ConfigEntryAuthFailed("Bad token") from ex      # → запустит reauth
except AccountClosedError as ex:
    raise ConfigEntryError("Unrecoverable") from ex        # навсегда
```
❌ Не ловить голый `Exception` → `ConfigEntryNotReady`. Маппить причины.

### 2.3 `action-setup` (Bronze) — сервисы в `async_setup`, НЕ в `async_setup_entry`
Сервисы должны существовать всегда (даже без загруженного entry), чтобы автоматизации валидировались. Валидация — внутри хендлера.
```python
async def async_setup(hass, config) -> bool:
    async def handle(call: ServiceCall) -> None:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if not entry or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("Entry not loaded")
        coordinator = entry.runtime_data
        ...
    hass.services.async_register(DOMAIN, SERVICE_X, handle, schema=SCHEMA)
    return True
```
❌ Регистрация в `async_setup_entry` + снятие в `async_unload_entry`.

### 2.4 `parallel-updates` (Silver) — задавать явно в каждой платформе
```python
# sensor.py / binary_sensor.py (read-only при coordinator):
PARALLEL_UPDATES = 0
# платформы с действиями (button/switch/number/select/...): осознанное число
PARALLEL_UPDATES = 1   # если устройство не любит параллельные запросы
```

### 2.5 `unique-config-entry` (Bronze) — ключ по серийнику, НЕ по host/IP
IP меняется → нельзя как unique_id. Брать стабильный идентификатор устройства.
```python
status = await api.get_status()
await self.async_set_unique_id(status["device"]["serial_number"])
self._abort_if_unique_id_configured(updates={CONF_HOST: host})  # обновим IP при reconfigure
```

### 2.6 `entity-unique-id` + `has-entity-name` (Bronze) — обязательны
`_attr_unique_id` у каждой сущности (стабильный, на базе серийника/entry); `_attr_has_entity_name = True` + перевод имени. ✅ у нас есть.

### 2.7 `entity-unavailable` + `log-when-unavailable` (Silver)
Сущность `available=False`, когда данных нет. Логировать недоступность **один раз** при падении и один раз при восстановлении — не спамить.

### 2.8 `reauthentication-flow` (Silver)
`async_step_reauth` / `async_step_reauth_confirm` в config flow; триггерится `ConfigEntryAuthFailed`.

### 2.9 `action-exceptions` (Silver) + translations (Gold)
Сервисы при ошибке кидают `ServiceValidationError` (ошибка ввода юзера) или `HomeAssistantError` (сбой). Для Gold — через `translation_domain`/`translation_key` (переводимые).

### 2.10 Библиотека на PyPI (Development checklist, core-блокер)
Всё общение с устройством/облаком — в **отдельной Python-библиотеке на PyPI** (с исходным sdist, включённым issue-tracker). Интеграция лишь использует её. ❌ Нельзя держать API-клиент (`api.py`) внутри интеграции для core. → выносим `busybar` в pip-пакет, прописываем в `requirements`.

### 2.11 Async / без блокирующего I/O (Platinum, но проверяется всегда)
Только async, без sync-HTTP/sleep/файловых блокировок в event loop. Зависимость поддерживает передачу `aiohttp` websession (`inject-websession`).

## 3. Полный чеклист правил (по тирам)

> Маркеры статуса для busybar: ✅ done · ❌ нарушено сейчас · ⬜ todo · ➖ exempt/n/a.
> Это живой gap-трекер; держать синхронным с `quality_scale.yaml`.

### 🥉 Bronze
- ⬜ `action-setup` — сервисы в `async_setup` (сейчас в entry ❌ → §2.3)
- ✅ `appropriate-polling` — интервал 5s осознанный
- ⬜ `brands` — лого в `home-assistant/brands`
- ⬜ `common-modules` — общие паттерны в общих модулях (coordinator/entity — ок)
- ⬜ `config-flow-test-coverage` — полное покрытие config flow тестами (тестов пока нет)
- 🟡 `config-flow` — есть; нужно добавить `data_description` к полям; корректно `data` vs `options`
- ⬜ `dependency-transparency` — зависимость прозрачна, на PyPI (см. §2.10)
- ⬜ `docs-actions` / `docs-high-level-description` / `docs-installation-instructions` / `docs-removal-instructions` — дока на home-assistant.io
- ✅ `entity-event-setup` — подписки в `async_added_to_hass` (CoordinatorEntity)
- ✅ `entity-unique-id`
- ✅ `has-entity-name`
- ❌ `runtime-data` — сейчас `hass.data` (§2.1)
- ✅ `test-before-configure` — config flow проверяет связь
- 🟡 `test-before-setup` — есть `async_config_entry_first_refresh`, но маппинг auth-ошибок отсутствует (§2.2)
- ❌ `unique-config-entry` — unique_id = host, надо serial (§2.5)

### 🥈 Silver
- 🟡 `action-exceptions` — кидаем `HomeAssistantError` (ок), `ServiceValidationError` для ввода — добавить
- ✅ `config-entry-unloading` — `async_unload_entry` есть
- ⬜ `docs-configuration-parameters` / `docs-installation-parameters`
- ⬜ `entity-unavailable` — частично; ревизия по всем сущностям
- ⬜ `integration-owner` — реальный `@codeowner` в manifest (сейчас плейсхолдер)
- ⬜ `log-when-unavailable` — once-on-fail / once-on-recover
- ❌ `parallel-updates` — не задано (§2.4)
- ⬜ `reauthentication-flow` — нет (§2.8)
- ⬜ `test-coverage` — >95% по всем модулям

### 🥇 Gold
- ✅ `devices` — создаём device
- ⬜ `diagnostics` — `diagnostics.py` (с редактированием секретов)
- ⬜ `discovery` + `discovery-update-info` — zeroconf/mDNS автопоиск бара + обновление IP
- ⬜ `dynamic-devices` / `stale-devices` — для account-mode (N баров): добавлять/удалять при изменениях
- 🟡 `entity-category` — частично (diagnostic у firmware/wifi); ревизия
- 🟡 `entity-device-class` — есть у части; ревизия
- ✅ `entity-disabled-by-default` — wifi выключен по умолчанию
- ✅ `entity-translations` — `translation_key` + en.json
- ⬜ `exception-translations` — переводимые исключения
- ⬜ `icon-translations` — `icons.json`
- ⬜ `reconfiguration-flow` — `async_step_reconfigure` (смена IP/токена)
- ⬜ `repair-issues` — repair-flow (напр. «бар не в Matter-фабрике» для smart_home)
- ⬜ docs-* (use-cases, examples, supported-devices/functions, known-limitations, troubleshooting, data-update)

### 🏆 Platinum
- 🟡 `async-dependency` — клиент async (после выноса в PyPI)
- 🟡 `inject-websession` — передаём `aiohttp` session (уже передаём в `api.py`)
- ⬜ `strict-typing` — `.strict-typing` + полная типизация, типизированный `ConfigEntry`

## 4. Процесс сабмита в core

1. Вынести API-клиент в PyPI-пакет; прописать в `manifest.json:requirements`.
2. Довести код до **Bronze** (все ❌/🟡 Bronze закрыты), желательно сразу Silver.
3. `quality_scale.yaml` заполнен; `manifest.json` корректный (`integration_type`, `iot_class`, реальный `codeowners`, `quality_scale`).
4. PR ассетов в `home-assistant/brands` (иконка/лого).
5. Дока-PR в `home-assistant.io`.
6. PR в `home-assistant/core`: проходит `hassfest`, `ruff`, тесты, ревью core-команды.
7. После мержа → заявка в «Works with Home Assistant» (нужно ≥ Gold).

## 5. BusyBar-специфика (don't regress)

- **snapshot = source of truth.** Управление таймером — через `PUT /api/busy/snapshot` (типы NOT_STARTED/INFINITE/SIMPLE/INTERVAL). Не выдумывать «параллельные» состояния.
- **ASCII-only на дисплее.** `TextElement.text` = `^[\x20-\x7E]+$`; не-ASCII → `?` (хелпер `_ascii`). Иначе 400.
- **Селектор (галетник) — write-only.** Позицию прочитать нельзя → `select` optimistic. Не делать вид, что читаем.
- **smart_home switch гейтить по Matter-fabric.** `fabric_count==0` → `available=False` (иначе 503).
- **draw на FW r799 → 400 (открытый баг).** Перед фиксом `notify`/`display_text`/`display_image` сверить актуальную схему `/api/display/draw`.
- **Cloud-mode = прокси.** `api.<env>.busy.app/busybar/<X>` ↔ локальный `/api/<X>`, auth `Bearer` (vs локальный `X-API-Token`). Полный remote-контроль. Account API `/timers/v1/*` — ещё не задеплоен.
- **Версии:** `sw_version` = `status.firmware.version` (`r799`), НЕ `api_semver`.
