# TeamTalk wrapper completeness (`core/teamtalk/ttbot.py` vs `core/teamtalk/TeamTalk5.py`)

This document tracks every callable capability that `core/teamtalk/TeamTalk5.py`
exposes (the raw ctypes SDK bindings) against how `core/teamtalk/ttbot.py`
(the `TTBot` class) surfaces it. It exists so that a future change to the raw
bindings, or a future audit, can tell at a glance what is covered and what was
skipped on purpose.

"Capability" here means: every method of the `TeamTalk` class in
`TeamTalk5.py` that actually calls one of the `TT_*` C functions (i.e. wraps
the SDK), plus the module-level functions that are meaningful to call from
bot code (`getVersion`, `setLicense`, `buildTextMessage`, `rebuildTextMessage`).
`TeamTalk.__init__`/`__del__`, the `on*` event-hook stubs, and pure debug/
internal helpers are enumerated separately below and are intentionally out of
scope (see "Deliberately skipped").

Counts as of this audit (part 1):

- Raw capabilities audited: **82** (78 `TeamTalk` methods that call a `TT_*`
  function + 4 relevant module-level functions)
- Already wrapped before this audit: **59**
- Newly wrapped in this audit: **23**
- Deliberately skipped (with reason): **46** (`TeamTalk.__init__`/`__del__`,
  `closeTeamTalk`, `runEventLoop`, 39 `on*` event hooks, and 3 internal
  module-level helpers: `ttstr`, `function_factory`, `DBG_SIZEOF`)

`tests/test_teamtalk_wrapper_coverage.py` enforces this table stays honest:
it parses both files with `ast` and asserts every `TeamTalk` method/relevant
module function is either called somewhere in `ttbot.py` or listed in the
skip whitelist in that test.

## `TeamTalk` class methods -> `TTBot` wrapper method(s)

| Raw capability (`TeamTalk.<method>`) | `TTBot` wrapper method(s) | Status |
|---|---|---|
| `getMessage` | `_wait_for_event`, `handle_messages`, `collect_full_message`, `_collect_until_success` | pre-existing |
| `getFlags` | `sound_output_ready` | pre-existing |
| `getDefaultSoundDevices` | `default_sound_devices` | **new** |
| `getSoundDevices` | `get_input_devices` | pre-existing |
| `initSoundInputDevice` | `set_input_device` | pre-existing |
| `initSoundOutputDevice` | `open_virtual_sound_output` | pre-existing |
| `closeSoundOutputDevice` | `close_sound_output` | pre-existing |
| `enableVoiceTransmission` | `set_microphone` | pre-existing |
| `setEncryptionContext` | `set_encryption_context` | **new** |
| `connect` | `connect` | pre-existing |
| `disconnect` | `disconnect` | pre-existing |
| `doPing` | `ping` | **new** |
| `doLogin` | `login` | pre-existing |
| `doLogout` | `logout` | pre-existing |
| `doJoinChannel` | `join_channel_struct` | **new** |
| `doJoinChannelByID` | `join` | pre-existing |
| `doLeaveChannel` | `leave_channel` | pre-existing |
| `doRemoveChannel` | `remove_channel` | pre-existing |
| `doSendFile` | `upload_file` | pre-existing |
| `doRecvFile` | `download_file` | pre-existing |
| `doDeleteFile` | `delete_file` | pre-existing |
| `doChangeNickname` | `set_name` | pre-existing |
| `doChangeStatus` | `set_status` | pre-existing |
| `doTextMessage` | `_send_one_with_retry` (used by `user_message`/`channel_message`/`broadcast_message`/`smart_message`) | pre-existing |
| `doChannelOp` | `make_channel_operator` | pre-existing |
| `doChannelOpEx` | `make_channel_operator` | pre-existing |
| `isChannelOperator` | `is_channel_operator` | pre-existing |
| `doKickUser` | `kick_user` | pre-existing |
| `doMoveUser` | `move_user` | pre-existing |
| `doBanUser` | `ban_user` | pre-existing |
| `doBanUserEx` | `ban_user_ex` | pre-existing |
| `doBan` | `ban_full` | **new** |
| `doBanIPAddress` | `ban_ip_address` | pre-existing |
| `doUnBanUser` | `unban_user` | pre-existing |
| `doUnbanUserEx` | `unban_full` | **new** |
| `doSubscribe` | `subscribe_to` | pre-existing |
| `doUnsubscribe` | `unsubscribe_from` | pre-existing |
| `doMakeChannel` | `create_channel` | pre-existing |
| `doUpdateChannel` | `update_channel` | pre-existing |
| `doUpdateServer` | `update_server_properties` | pre-existing |
| `doListUserAccounts` | `list_user_accounts` | pre-existing |
| `doNewUserAccount` | `create_user_account` | pre-existing |
| `doDeleteUserAccount` | `delete_user_account` | pre-existing |
| `doListBans` | `list_bans` | pre-existing |
| `doSaveConfig` | `save_server_config` | pre-existing |
| `doQueryServerStats` | `query_server_stats` | pre-existing |
| `doQuit` | `notify_quit` | **new** |
| `getServerProperties` | `server_properties`, `update_server_properties` | pre-existing |
| `getServerUsers` | `get_server_users` | pre-existing |
| `getRootChannelID` | `get_root_channel_id`, `create_channel`, `_join_path` | pre-existing |
| `getMyChannelID` | `get_my_channel_id` | pre-existing |
| `getChannel` | `get_channel`, `update_channel` | pre-existing |
| `getChannelPath` | `get_channel_path`, `_join_path` | pre-existing |
| `getChannelIDFromPath` | `get_channel_id_from_path`, `create_channel` | pre-existing |
| `getChannelUsers` | `get_channel_users` | pre-existing |
| `getChannelFiles` | `list_channel_files` | pre-existing |
| `getServerChannels` | `list_channels` | pre-existing |
| `getMyUserID` | `my_id`, `get_user_info` | pre-existing |
| `getMyUserType` | `is_server_admin` | pre-existing |
| `getMyUserAccount` | `my_user_account` | pre-existing |
| `getMyUserData` | `my_user_data` | **new** |
| `getUser` | `get_user_info`, `get_user_subscriptions`, `_dispatch_message` | pre-existing |
| `getUserStatistics` | `get_user_statistics` | **new** |
| `getUserByUsername` | `get_user_by_username` | pre-existing |
| `getErrorMessage` | `error_message` | **new** |
| `setUserMediaStorageDir` | `set_user_media_storage_dir` | **new** |
| `setUserStoppedPlaybackDelay` | `set_user_stopped_playback_delay` | **new** |
| `startStreamingMediaFileToChannel` | `start_streaming_media_file` | **new** |
| `stopStreamingMediaFileToChannel` | `stop_streaming_media_file` | **new** |
| `initLocalPlayback` | `init_local_playback` | **new** |
| `updateLocalPlayback` | `update_local_playback` | **new** |
| `stopLocalPlayback` | `stop_local_playback` | **new** |
| `enableAudioBlockEvent` | `enable_audio_blocks` | pre-existing |
| `enableAudioBlockEventEx` | `enable_audio_block_event_ex` | **new** |
| `insertAudioBlock` | `insert_audio_block` | **new** |
| `acquireUserAudioBlock` | `acquire_audio_block` | pre-existing |
| `releaseUserAudioBlock` | `acquire_audio_block` | pre-existing |
| `getMediaFileInfo` | `media_file_info` (works around a raw-binding bug, see below) | **new** |

### Note on `getMediaFileInfo`

`TeamTalk5.py` defines `TeamTalk.getMediaFileInfo` without a `self`
parameter (`def getMediaFileInfo(szMediaFilePath) -> MediaFileInfo:`), so
calling it as an instance method (`self.tt.getMediaFileInfo(path)`) raises
`TypeError` (Python auto-binds `self` as the first argument). `TTBot.media_file_info`
works around this by calling it through the class instead of the instance
(`type(self.tt).getMediaFileInfo(path)`), which matches the function's real,
instance-independent signature (`TT_GetMediaFileInfo` only takes a path, no
SDK instance handle). This is a pre-existing bug in the vendored
`TeamTalk5.py` bindings; per the task scope, that file is not modified here.

## Module-level functions -> `TTBot` wrapper method(s)

| Raw capability | `TTBot` wrapper method | Status |
|---|---|---|
| `getVersion()` | `sdk_version` | **new** |
| `setLicense(name, key)` | `set_license` | **new** |
| `buildTextMessage(...)` | used internally by `_send_chunks` (and therefore `user_message`/`channel_message`/`broadcast_message`/`smart_message`) | pre-existing (indirect) |
| `rebuildTextMessage(msgs)` | `rebuild_message` | **new** |

## Deliberately skipped (with reason)

| Raw capability | Reason skipped |
|---|---|
| `TeamTalk.__init__` | Instance/session lifecycle, already invoked automatically by `TTBot.__init__` (`self.tt = TeamTalk()`); not a separate bot-facing action. |
| `TeamTalk.__del__` | Python object teardown hook; calls `closeTeamTalk` automatically, never meant to be called directly. |
| `closeTeamTalk` | Tears down the native TeamTalk instance. Only `TeamTalk.__del__` should call this; exposing it separately on `TTBot` would let callers destroy the SDK instance out from under a live bot, corrupting the native layer. |
| `runEventLoop` | An alternative built-in event-dispatch loop (calls the `on*` hooks below). `ttbot.py` deliberately replaced this with its own dispatch (`handle_messages` / `_dispatch_message` / `EVENT_MAP` / `subscribe`), which supports pending-event buffering, audio-block draining and per-event-name subscriber callbacks that `runEventLoop` does not. Wrapping it would just reintroduce a second, unused, competing dispatch path. |
| `onConnectSuccess`, `onConnectCryptError`, `onConnectFailed`, `onConnectionLost`, `onCmdProcessing`, `onCmdError`, `onCmdSuccess`, `onCmdMyselfLoggedIn`, `onCmdMyselfLoggedOut`, `onCmdMyselfKickedFromChannel`, `onCmdUserLoggedIn`, `onCmdUserLoggedOut`, `onCmdUserUpdate`, `onCmdUserJoinedChannel`, `onCmdUserLeftChannel`, `onCmdChannelNew`, `onCmdChannelUpdate`, `onCmdChannelRemove`, `onCmdUserTextMessage`, `onCmdServerUpdate`, `onCmdFileNew`, `onCmdFileRemove`, `onUserRecordMediaFile`, `onUserAccountNew`, `onUserAccountRemove`, `onUserStateChange`, `onUserAudioBlock`, `onStreamMediaFile`, `onUserAccount`, `onBannedUser`, `onServerStatistics`, `onInternalError`, `onSoundDeviceAdded`, `onSoundDeviceRemoved`, `onSoundDeviceUnplugged`, `onSoundDeviceNewDefaultInput`, `onSoundDeviceNewDefaultOutput`, `onSoundDeviceNewDefaultInputComDevice`, `onSoundDeviceNewDefaultOutputComDevice` (39 methods) | Overridable no-op hooks that only `runEventLoop` calls (see above); they wrap no `TT_*` function themselves. Since `ttbot.py` never calls `runEventLoop`, these hooks are dead code from `TTBot`'s point of view -- its own `EVENT_MAP`/`_dispatch_message` covers the same events (and more, e.g. sound-device and ban/account events) with richer, already-parsed-to-`dict` payloads. |
| `ttstr` (module-level) | Internal string/encoding helper, already used throughout `ttbot.py` on every field read/write; it is the mechanism other wrappers use, not a capability of its own to wrap. |
| `function_factory` (module-level) | Internal ctypes plumbing used only while `TeamTalk5.py` defines its `_TT_*` bindings at import time; nothing a bot would call. |
| `DBG_SIZEOF` (module-level) | Internal struct-size self-check, called by every `Structure.__init__` in `TeamTalk5.py` to assert the Python ctypes layout matches the SDK's C layout. It is a build/binding sanity check, not a bot-facing action. |
