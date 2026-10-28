# پوشش `core/mpv/player.py` روی `core/mpv/mpv.py`

این سند نتیجه‌ی ادیت کامل‌سازیِ رپر (part 2) رو ثبت می‌کنه: هر قابلیت عمومیِ
`core/mpv/mpv.py` (کتابخونه‌ی خامِ python-mpv) که `core/mpv/player.py` بهش دسترسی
می‌ده، یا اگه عمداً پوشش داده نشده، چرا.

`core/mpv/mpv.py` دست‌نخورده می‌مونه؛ این کار فقط لایه‌ی `Player` رو کامل کرده.

## خلاصه‌ی عددی

- کل قابلیت‌های عمومیِ کلاس `MPV` (متد + پراپرتی صریح): **103**
- قبل از این ادیت پوشش داده شده بودن (ادیت اول): **22**
- توی همین ادیت اضافه شدن: **80**
- عمداً skip شدن (با دلیل، پایین‌تر): **1** (`properties`)
- علاوه بر این‌ها، یه جفت متد عمومیِ `get_property`/`set_property` هم اضافه
  شده که دسترسیِ خام به هر کدوم از **صدها پراپرتیِ داینامیکِ** خودِ libmpv
  رو می‌ده (چیزهایی مثل `volume`، `time-pos`، `vid`، ...که همه از طریق
  `__getattr__`/`__setattr__` خودِ `MPV` در دسترسن، نه این‌که هرکدوم توی
  کلاس `MPV` به‌صورت یه `@property` صریح تعریف شده باشن -- برای همین جزو اون
  ۱۰۳ تا شمرده نمی‌شن ولی پوشش‌شون از این رپر رد می‌شه).

جدول کامل و لیست skip پایین‌تره. تست `tests/test_mpv_wrapper_coverage.py`
دقیقاً همین لیست رو (با ast، بدون import کردنِ واقعیِ mpv.py) می‌سازه و چک
می‌کنه که چیزی جا نمونده باشه؛ اگه یه متد/پراپرتی جدید به `core/mpv/mpv.py`
اضافه بشه و اینجا/توی whitelist پوشش داده نشه، اون تست قرمز می‌شه.

## قاعده‌ی کلی

- هر متد/پراپرتی خامِ `MPV` یا یه متد/پراپرتیِ هم‌نام (یا هم‌معنی‌ترِ) روی
  `Player` می‌گیره که مستقیم به `self.raw.<name>` پاس می‌ده -- بدون منطق
  اضافه، بدون تغییر رفتار.
- هیچ observer/thread/callback‌ای خودکار ثبت نمی‌شه؛ چیزهایی مثل
  `observe_property`, `register_event_callback`, `on_key_press` فقط وقتی
  فعال می‌شن که خودِ صدازننده صریحاً یکی از این متدها رو صدا بزنه.
- قابلیت‌های فقط-ویدیویی (overlay، mouse، keypress، discnav، ...) هم پوشش
  داده شدن چون هزینه‌ی wrap کردن‌شون صفره (فقط یه پاس‌دهی)، حتی اگه با
  `vo="null"` (پیش‌فرض این رپر برای بات صوتی) عملاً بی‌اثر باشن.

## جدول کامل (خام → رپر)

| قابلیت خام (`mpv.py`) | نوع | متد/پراپرتی روی `Player` |
|---|---|---|
| `check_core_alive` | method | `is_core_alive()` |
| `wait_until_paused` | method | `wait_until_paused()` |
| `wait_for_playback` | method | `wait_until_playing()` *(ادیت اول)* |
| `wait_until_playing` | method | `wait_for_playback_start()` |
| `wait_for_property` | method | `wait_for_property()` |
| `wait_for_shutdown` | method | `wait_for_shutdown()` |
| `prepare_and_wait_for_property` | method | `wait_for_property_context()` |
| `wait_for_event` | method | `wait_for_event()` *(ادیت اول)* |
| `prepare_and_wait_for_event` | method | `wait_for_event_context()` |
| `terminate` | method | `terminate()` *(ادیت اول)* |
| `set_loglevel` | method | `set_log_level()` |
| `string_command` | method | `run_command_string()` |
| `command_async` | method | `run_command_async()` |
| `node_command` | method | `run_node_command()` |
| `command` | method | `run_command()` (و `next_chapter`/`previous_chapter`/`set_equalizer` از ادیت اول) |
| `seek` | method | `seek_relative()` / `seek_to()` *(ادیت اول)* |
| `revert_seek` | method | `revert_seek()` |
| `frame_step` | method | `step_frame_forward()` |
| `frame_back_step` | method | `step_frame_backward()` |
| `property_add` | method | `adjust_property()` |
| `property_multiply` | method | `multiply_property()` |
| `cycle` | method | `cycle_property()` |
| `screenshot` | method | `take_screenshot()` *(ادیت اول)* |
| `screenshot_to_file` | method | `take_screenshot()` *(ادیت اول)* |
| `screenshot_raw` | method | `take_screenshot_image()` |
| `allocate_overlay_id` | method | `allocate_overlay_id()` |
| `free_overlay_id` | method | `free_overlay_id()` |
| `create_file_overlay` | method | `create_file_overlay()` |
| `create_image_overlay` | method | `create_image_overlay()` |
| `remove_overlay` | method | `remove_overlay()` |
| `playlist_next` | method | `next()` *(ادیت اول)* |
| `playlist_prev` | method | `previous()` *(ادیت اول)* |
| `playlist_play_index` | method | `jump_to()` *(ادیت اول)* |
| `loadfile` | method | `load_file()` |
| `loadlist` | method | `load_playlist_file()` |
| `playlist_clear` | method | `clear_queue()` *(ادیت اول)* |
| `playlist_remove` | method | `remove_from_queue()` *(ادیت اول)* |
| `playlist_move` | method | `move_in_queue()` *(ادیت اول)* |
| `playlist_shuffle` | method | `shuffle_queue()` *(ادیت اول)* |
| `playlist_unshuffle` | method | `unshuffle_queue()` *(ادیت اول)* |
| `run` | method | `run_subprocess()` |
| `quit` | method | `quit()` |
| `quit_watch_later` | method | `quit_and_save_position()` |
| `stop` | method | `stop()` *(ادیت اول)* |
| `audio_add` | method | `add_audio_track()` *(ادیت اول)* |
| `audio_remove` | method | `remove_audio_track()` |
| `audio_reload` | method | `reload_audio_track()` |
| `video_add` | method | `add_video_track()` |
| `video_remove` | method | `remove_video_track()` |
| `video_reload` | method | `reload_video_track()` |
| `sub_add` | method | `add_subtitle()` *(ادیت اول)* |
| `sub_remove` | method | `remove_subtitle()` |
| `sub_reload` | method | `reload_subtitle()` |
| `sub_step` | method | `step_subtitle()` |
| `sub_seek` | method | `seek_subtitle()` |
| `toggle_osd` | method | `toggle_osd()` |
| `print_text` | method | `print_text()` |
| `show_text` | method | `show_text()` |
| `expand_text` | method | `expand_text()` |
| `expand_path` | method | `expand_path()` |
| `show_progress` | method | `show_progress()` |
| `rescan_external_files` | method | `rescan_external_files()` |
| `discnav` | method | `send_discnav_command()` |
| `mouse` | method | `send_mouse_event()` |
| `keypress` | method | `send_keypress()` |
| `keydown` | method | `send_keydown()` |
| `keyup` | method | `send_keyup()` |
| `keybind` | method | `bind_key_to_command()` |
| `write_watch_later_config` | method | `write_watch_later_config()` |
| `overlay_add` | method | `add_raw_overlay()` |
| `overlay_remove` | method | `remove_raw_overlay()` |
| `osd_overlay` | method | `set_osd_overlay()` |
| `osd_overlay_remove` | method | `clear_osd_overlay()` |
| `script_message` | method | `send_script_message()` |
| `script_message_to` | method | `send_script_message_to()` |
| `drop_buffers` | method | `drop_buffers()` |
| `vf_command` | method | `run_video_filter_command()` |
| `af_command` | method | `run_audio_filter_command()` |
| `observe_property` | method | `on_property_change()` *(ادیت اول)* |
| `property_observer` | method | `property_observer()` |
| `unobserve_property` | method | `remove_property_observer()` |
| `unobserve_all_properties` | method | `remove_all_property_observers()` |
| `register_message_handler` | method | `register_script_message_handler()` |
| `unregister_message_handler` | method | `unregister_script_message_handler()` |
| `message_handler` | method | `script_message_handler()` |
| `register_event_callback` | method | `add_event_callback()` |
| `unregister_event_callback` | method | `remove_event_callback()` |
| `event_callback` | method | `on_event()` *(ادیت اول)* |
| `on_key_press` | method | `bind_key_press()` |
| `key_binding` | method | `bind_key()` |
| `register_key_binding` | method | `register_key_callback()` |
| `unregister_key_binding` | method | `unbind_key()` |
| `register_stream_protocol` | method | `register_stream_protocol()` |
| `play` | method | `play()` *(ادیت اول)* |
| `playlist_append` | method | `enqueue()` *(ادیت اول)* |
| `python_stream` | method | `register_python_stream()` |
| `play_context` | method | `stream_writer()` |
| `play_bytes` | method | `play_bytes()` |
| `python_stream_catchall` | method | `set_stream_catchall()` |
| `option_info` | method | `get_option_info()` |
| `core_shutdown` | property | `is_core_shutdown` |
| `playlist_filenames` | property | `queue_filenames` |
| `properties` | property | **skip -- دلیل پایینه** |

علاوه‌بر جدول بالا، ده‌ها پراپرتیِ داینامیکِ دیگه‌ی خودِ libmpv (`volume`,
`pause`, `mute`, `time-pos`, `duration`, `vid`, `sid`, `aid`, `speed`, ...)
از قبل با اسم‌های خودشون یا اسم‌های واضح‌تر روی `Player` پوشش داده شدن
(بخش‌های بالای این فایل)، و هرکدوم که اسم اختصاصی نداشته باشن از طریق جفت
عمومیِ `get_property(name)` / `set_property(name, value)` در دسترسن.

## چیزی که عمداً skip شده

| قابلیت | دلیل |
|---|---|
| `MPV.properties` | این پراپرتی برای *هر* پراپرتیِ libmpv (چند صد تا) یه `option_info` جدا صدا می‌زنه -- یعنی یه عملیات کند و سنگین که برای «هزاران بات روی یه سرور» اصلاً نباید یه راه راحت/یه‌خطی داشته باشه که تصادفی سرِ راه صدا زده بشه. کسی که واقعاً به این نیاز داره (ابزار دیباگ/اینترواسپکشن، نه مسیر داغ ربات) می‌تونه مستقیم `player.raw.properties` رو صدا بزنه؛ `self.raw` طبق فلسفه‌ی این فایل همیشه در دسترسه. |

هیچ قابلیت ویدیویی/overlay/کیبورد دیگه‌ای skip نشده: هرچند بی‌فایده‌ان وقتی
`vo="null"` (پیش‌فرض این رپر)، هزینه‌ی wrap کردن‌شون صفره، و اگه یه پروژه‌ی
دیگه با `video_output="gpu"` از همین `Player` استفاده کنه، همه کار می‌کنن.

## تست‌ها

- `tests/test_mpv_wrapper_delegation.py`: جدولی از رپرهای جدید، با یه
  شیء raw جعلی (بدون هیچ لود واقعیِ libmpv)، چک می‌کنه که هر رپر دقیقاً
  همون متد/پراپرتیِ raw رو با همون آرگومان‌ها صدا می‌زنه.
- `tests/test_mpv_wrapper_coverage.py`: با `ast` (نه import) هم کلاس `MPV`
  توی `core/mpv/mpv.py` و هم کلاس `Player` توی `core/mpv/player.py` رو می‌خونه و چک
  می‌کنه هر قابلیت عمومیِ خام یا صدا زده می‌شه یا توی whitelist مستندشده
  (همین فایل) هست -- یعنی اگه یه ادیت بعدی یه قابلیت جدید به `mpv.py`
  اضافه کنه و کسی رپرش نکنه، این تست قرمز می‌شه.
