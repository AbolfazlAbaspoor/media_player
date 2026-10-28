from .TeamTalk5 import *
import ctypes
import time
import threading
from collections import defaultdict, deque

from core import logging_setup

class TeamTalkCommandError(Exception):
	"""
	وقتی سرور صریحاً یه خطا (CLIENTEVENT_CMD_ERROR) برمی‌گردونه (نه فقط
	timeout بی‌دلیل)، این exception با کد و متن خطای واقعی سرور raise
	می‌شه؛ صدا زننده می‌تونه با error_code (اعداد ClientError.CMDERR_*)
	تشخیص بده که خطا موقتیه (قابل retry) یا همیشگی (مثلاً بن شدن، اکانت
	حذف‌شده، پسورد اشتباه) که دیگه retry فایده‌ای نداره.
	"""
	def __init__(self, error_code, error_message=""):
		self.error_code = error_code
		self.error_message = error_message
		super().__init__(f"Server error {error_code}: {error_message}")

class TTBot:
	def __init__(self):
		self.tt = TeamTalk()
		self.server_info = {}
		self.subscribers = defaultdict(list)
		self.event_buffer = deque(maxlen=200)
		# رویدادهایی که موقع انتظار برای جواب یه دستور (مثلاً login/join)
		# از صف بیرون کشیده شدن ولی ربطی به اون انتظار نداشتن. قبلاً این‌ها
		# دور ریخته می‌شدن -- یعنی هر پیام/دستوری که کاربر دقیقاً توی اون
		# لحظه می‌فرستاد، برای همیشه گم می‌شد. حالا نگهشون می‌داریم و
		# handle_messages اول همین‌ها رو پردازش می‌کنه.
		self._pending_events = deque(maxlen=500)
		self.mic_open = False
		self._send_lock = threading.Lock()
		self._tt_lock = threading.RLock()

		# --- پیام‌رسانی هوشمند: rate-limit + retry + صف پیام‌های ناموفق ---
		self._msg_send_times = deque(maxlen=64)
		self._msg_rate_lock = threading.Lock()
		self._failed_messages = deque(maxlen=200)
		self._retry_worker_running = False
		self._retry_worker_lock = threading.Lock()

		# کاربرهایی که همین الان صداشون عمداً گرفته می‌شه (جستجوی صوتی،
		# core/voice_search.py). minimize_subscriptions اشتراک صدای این‌ها
		# رو قطع نمی‌کنه، تا وسط ضبط کسی (مثلاً یه minimize دیرهنگام) صدا رو نبره.
		self._voice_holds = set()
		self._voice_holds_lock = threading.Lock()

	# --- تنظیمات rate-limit/retry (قابل override روی instance در صورت نیاز) ---
	MSG_RATE_LIMIT_WINDOW = 5.0     # ثانیه
	# نکته‌ی مهم: send_long_text (q/help/al/cp/...) می‌تونه یه لیست بلند رو
	# به ده‌ها پیام جدا (هرکدوم زیر ۵۱۲ کاراکتر) بشکنه و همه رو پشت‌سرهم
	# بفرسته -- این یه استفاده‌ی مشروعه، نه flood. سقف باید اونقدر بالا
	# باشه که این حالت رو throttle نکنه، ولی بازم جلوی یه لوپ واقعاً
	# خراب/بی‌نهایت رو بگیره.
	MSG_RATE_LIMIT_MAX = 60         # حداکثر پیام در این بازه، قبل از throttle شدن
	MSG_CHUNK_DELAY = 0.05          # فاصله بین تکه‌های یک پیام طولانی (bMore)
	MSG_MAX_RETRIES = 3
	MSG_RETRY_BACKOFF = 0.4         # ثانیه، هر بار retry دوبرابر می‌شه
	MSG_QUEUE_MAX_AGE = 300         # ثانیه؛ پیام ناموفق‌تر از این، دور ریخته می‌شه

	def subscribe_to(self, user_id, subscriptions, wait=False):
		"""
		subscriptions یه OR از Subscription.SUBSCRIBE_* هاست.

		wait=False (پیش‌فرض) یعنی فقط دستور رو می‌فرستیم و برمی‌گردیم.
		منتظر موندن برای تأیید سرور به‌ازای هر کاربر، روی سرورهای شلوغ
		استارت ربات رو دقیقه‌ها طول می‌داد؛ و چون این عملیات فقط یه
		بهینه‌سازی مصرف پهنای‌باندست، تأیید گرفتنش ارزش بلاک‌کردن نداره.
		"""
		with self._tt_lock:
			cmd_id = self.tt.doSubscribe(user_id, subscriptions)
			if cmd_id <= 0:
				return False
			if not wait:
				return True
			ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SUCCESS, 3000)
			return ok

	def unsubscribe_from(self, user_id, subscriptions, wait=False):
		"""
		subscriptions یه OR از Subscription.SUBSCRIBE_* هاست.

		نکته: doUnsubscribe غیرهمزمانه؛ اگه بلافاصله بعدش getUser() رو چک
		کنی، ممکنه هنوز مقدار قدیمی رو ببینی. با wait=True می‌شه منتظر
		تأیید واقعی سرور موند، ولی پیش‌فرض غیرمسدودکننده‌ست (دلیلش توی
		subscribe_to توضیح داده شده).
		"""
		with self._tt_lock:
			cmd_id = self.tt.doUnsubscribe(user_id, subscriptions)
			if cmd_id <= 0:
				return False
			if not wait:
				return True
			ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SUCCESS, 3000)
			return ok

	def minimize_subscriptions(self, user_id, wait=False):
		"""
		فقط پیام خصوصی کاربر (لازم برای گرفتن دستورات چت) رو نگه می‌داره؛
		بقیه‌ی استریم‌ها (صدا/تصویر/دسکتاپ/ورودی‌دسکتاپ/فایل مدیا/پیام
		کانال/broadcast) رو قطع می‌کنه. چون این ربات فقط پخش می‌کنه، هیچ‌وقت
		نیازی به گرفتن این استریم‌ها از بقیه‌ی کاربرها نداره؛ قطع‌کردنشون
		مستقیم مصرف اینترنت/CPU رو کم می‌کنه.

		استثنا: کاربری که hold_voice براش صدا زده شده (جستجوی صوتیِ در
		جریان) اشتراک صداش دست نمی‌خوره؛ خودِ جستجوی صوتی آخر کار قطعش می‌کنه.
		"""
		flags = (
			Subscription.SUBSCRIBE_CHANNEL_MSG
			| Subscription.SUBSCRIBE_BROADCAST_MSG
			| Subscription.SUBSCRIBE_VOICE
			| Subscription.SUBSCRIBE_VIDEOCAPTURE
			| Subscription.SUBSCRIBE_DESKTOP
			| Subscription.SUBSCRIBE_DESKTOPINPUT
			| Subscription.SUBSCRIBE_MEDIAFILE
		)
		if self.is_voice_held(user_id):
			flags &= ~Subscription.SUBSCRIBE_VOICE
		return self.unsubscribe_from(user_id, flags, wait=wait)

	# --- جستجوی صوتی: گرفتن صدای *یک* کاربر، فقط برای چند ثانیه -------------
	#
	# ربات به‌طور عادی صدای هیچ‌کس رو نمی‌گیره. core/voice_search.py برای
	# یه جستجو این‌ها رو به‌ترتیب صدا می‌زنه و آخر کار (موفق، timeout، خطا،
	# قطع اتصال) همه رو برعکس می‌کنه.
	#
	# ایمنی پخش: SDK صدای کاربر رو فقط وقتی decode می‌کنه که یه دستگاه
	# *خروجی* تیم‌تاک باز باشه (ClientUser::LaunchAudioPlayer بدون دستگاه
	# خروجی اصلاً player نمی‌سازه، پس نه AudioBlock میاد نه USERSTATE_VOICE).
	# برای همین دستگاه مجازی خودِ تیم‌تاک (TT_SOUNDDEVICE_ID_TEAMTALK_VIRTUAL)
	# باز می‌شه: صدا رو decode می‌کنه ولی به هیچ کارت صدا/لاین واقعی‌ای
	# نمی‌فرسته، پس صدای کاربر هیچ‌وقت به لاینی که ربات ازش پخش می‌کنه
	# نمی‌رسه. mute/volume=0 راه‌حل نیست: توی SDK 5.22 بهره‌ی همون mute/volume
	# روی خودِ AudioBlock هم اعمال می‌شه (AudioFrame::ApplyGain) و فقط سکوت
	# ضبط می‌شد.

	def hold_voice(self, user_id):
		with self._voice_holds_lock:
			self._voice_holds.add(user_id)

	def release_voice(self, user_id):
		with self._voice_holds_lock:
			self._voice_holds.discard(user_id)

	def is_voice_held(self, user_id):
		with self._voice_holds_lock:
			return user_id in self._voice_holds

	def listen_to_voice(self, user_id, intercept=False):
		"""
		اشتراک صدای یه کاربر. intercept=True (فقط برای کاربر نوع ادمین
		مجازه) صدای کاربری رو که توی کانال ربات نیست هم می‌گیره.
		"""
		flag = Subscription.SUBSCRIBE_INTERCEPT_VOICE if intercept else Subscription.SUBSCRIBE_VOICE
		return self.subscribe_to(user_id, flag)

	def stop_listening_to_voice(self, user_id, intercept=False):
		"""فقط همون اشتراکی که listen_to_voice گرفته بود قطع می‌شه."""
		flag = Subscription.SUBSCRIBE_INTERCEPT_VOICE if intercept else Subscription.SUBSCRIBE_VOICE
		return self.unsubscribe_from(user_id, flag)

	def enable_audio_blocks(self, user_id, enable=True, stream_type=StreamType.STREAMTYPE_VOICE):
		"""رویداد CLIENTEVENT_USER_AUDIOBLOCK رو برای صدای یه کاربر روشن/خاموش می‌کنه."""
		return bool(self.tt.enableAudioBlockEvent(user_id, stream_type, bool(enable)))

	def sound_output_ready(self):
		"""آیا یه دستگاه خروجی تیم‌تاک (هر دستگاهی) همین الان بازه؟"""
		return bool(self.tt.getFlags() & ClientFlags.CLIENT_SNDOUTPUT_READY)

	def open_virtual_sound_output(self):
		"""دستگاه خروجی مجازی تیم‌تاک: decode بدون پخش روی هیچ دستگاه واقعی."""
		return bool(self.tt.initSoundOutputDevice(TT_SOUNDDEVICE_ID_TEAMTALK_VIRTUAL))

	def close_sound_output(self):
		return bool(self.tt.closeSoundOutputDevice())

	def recording_blocked(self):
		"""
		آیا کانالِ فعلیِ ربات «No recording» (CHANNEL_NO_RECORDING) است و ربات
		ادمینِ سرور نیست؟

		توی چنین کانالی SDK صدای بقیه رو decode می‌کنه (USERSTATE_VOICE یعنی
		«داره حرف می‌زنه» میاد) ولی بلوک‌های صدا رو نمی‌ده -- یعنی جستجوی صوتی
		حرف‌زدن رو می‌بینه ولی هیچ صدایی نمی‌گیره و همیشه «خیلی کوتاه» می‌گه.

		اپراتورِ کانال بودن کافی نیست: روی سرورِ واقعی، ربات بعد از اپراتور
		شدن هنوز enableAudioBlockEvent=True ولی صفر بلوک می‌گرفت
		(blocks=0, talking_events=2).

		استثناها: ادمینِ سرور، یا حسابی که دسترسیِ «Record voice»
		(USERRIGHT_RECORD_VOICE) داره -- همون دسترسیِ باریکی که تیم‌تاک
		دقیقاً برای «فقط این حساب بتونه توی کانالِ No recording ضبط کنه»
		گذاشته. مدیرِ سرور می‌تونه فقط همین رو به ربات بده، بدونِ ادمین یا
		اپراتور کردنش، و کانال برای بقیه همچنان ضبط‌ممنوع می‌مونه.
		"""
		with self._tt_lock:
			channel_id = self.tt.getMyChannelID()
			if not channel_id:
				return False
			channel = self.tt.getChannel(channel_id)
			if not channel or not (channel.uChannelType & ChannelType.CHANNEL_NO_RECORDING):
				return False
			if self.tt.getMyUserType() & UserType.USERTYPE_ADMIN:
				return False
			try:
				rights = int(self.tt.getMyUserAccount().uUserRights)
			except Exception:
				rights = 0
			return not (rights & UserRight.USERRIGHT_RECORD_VOICE)

	def is_server_admin(self):
		"""آیا خودِ ربات با یه حساب نوع ادمین لاگین کرده؟ (شرط intercept)"""
		return bool(self.tt.getMyUserType() & UserType.USERTYPE_ADMIN)

	# سقف بلوک‌هایی که با یه رویداد خالی می‌شن (محافظ حلقه‌ی بی‌پایان).
	AUDIO_BLOCK_DRAIN_LIMIT = 64
	# یه AudioBlock چند ده میلی‌ثانیه‌ست؛ هر چیز خیلی بزرگ‌تر یعنی ساختار خراب.
	AUDIO_BLOCK_MAX_BYTES = 16 * 1024 * 1024

	def acquire_audio_block(self, user_id, stream_type=StreamType.STREAMTYPE_VOICE):
		"""
		یه AudioBlock برمی‌داره، PCM رو *کپی* می‌کنه و بلافاصله آزادش می‌کنه
		(حافظه‌اش مال SDK است و بعد از release نباید بهش دست زد).
		خروجی dict یا None (بلوکی نمونده).
		"""
		ptr = self.tt.acquireUserAudioBlock(stream_type, user_id)
		if not ptr:
			return None
		try:
			block = ptr.contents
			sample_rate = int(block.nSampleRate)
			channels = int(block.nChannels)
			size = int(block.nSamples) * channels * 2
			if block.lpRawAudio and 0 < size <= self.AUDIO_BLOCK_MAX_BYTES:
				pcm = ctypes.string_at(block.lpRawAudio, size)
			else:
				pcm = b""
			stream_id = int(block.nStreamID)
		finally:
			self.tt.releaseUserAudioBlock(ptr)
		return {
			"user_id": user_id,
			"sample_rate": sample_rate,
			"channels": channels,
			"pcm": pcm,
			"stream_type": int(stream_type),
			"stream_id": stream_id,
		}

	def drain_audio_blocks(self, user_id, stream_type=StreamType.STREAMTYPE_VOICE):
		"""
		همه‌ی بلوک‌های صف این کاربر. SDK برای هر کاربر فقط ~۱۲۸ کیلوبایت نگه
		می‌داره، پس با هر رویداد کل صف خالی می‌شه تا اگه چند رویداد دیر
		رسیدن، صدا از دست نره (رویدادهای بعدی فقط صفِ خالی می‌بینن).
		"""
		blocks = []
		for _ in range(self.AUDIO_BLOCK_DRAIN_LIMIT):
			block = self.acquire_audio_block(user_id, stream_type)
			if block is None:
				break
			blocks.append(block)
		return blocks

	def _handle_audio_block_event(self, msg):
		"""
		رویداد صدا هر جا که از صف SDK بیرون کشیده بشه (حلقه‌ی اصلی، یا وسط
		انتظار برای جواب یه دستور) همون‌جا پردازش می‌شه، نه این‌که توی
		_pending_events بمونه: ۵۰ رویداد در ثانیه اون صف ۵۰۰تایی رو پر می‌کرد
		و پیام/دستور واقعی کاربرها از سرش بیرون می‌افتاد.
		"""
		try:
			self._dispatch_message(msg)
		except Exception:
			try:
				logging_setup.log_exception("handling a TeamTalk audio block")
			except Exception:
				pass

	def get_user_subscriptions(self, user_id):
		"""
		وضعیت واقعیِ الان (نه چیزی که فکر می‌کنیم فرستادیم) رو مستقیم از
		SDK می‌خونه: uLocalSubscriptions یعنی «ما همین الان واقعاً از این
		کاربر چی رو داریم می‌گیریم». برای اطمینان از این‌که
		minimize_subscriptions واقعاً جواب داده، همینو چک کن، نه فقط
		return code خودِ doUnsubscribe.
		"""
		with self._tt_lock:
			u = self.tt.getUser(user_id)
			if not u:
				return None
			mask = u.uLocalSubscriptions
			return {
				"channel_msg": bool(mask & Subscription.SUBSCRIBE_CHANNEL_MSG),
				"broadcast_msg": bool(mask & Subscription.SUBSCRIBE_BROADCAST_MSG),
				"voice": bool(mask & Subscription.SUBSCRIBE_VOICE),
				"video": bool(mask & Subscription.SUBSCRIBE_VIDEOCAPTURE),
				"desktop": bool(mask & Subscription.SUBSCRIBE_DESKTOP),
				"desktop_input": bool(mask & Subscription.SUBSCRIBE_DESKTOPINPUT),
				"media_file": bool(mask & Subscription.SUBSCRIBE_MEDIAFILE),
				"raw_mask": mask,
			}

	def get_user_info(self, user_id=None):
		with self._tt_lock:
			if user_id is None:
				user_id = self.tt.getMyUserID()
			u = self.tt.getUser(user_id)
			if not u:
				raise Exception("User not found")
			return {
			"user_id": u.nUserID,
			"username": ttstr(u.szUsername),
			"nickname": ttstr(u.szNickname),
			"channel_id": u.nChannelID,
			"status_mode": u.nStatusMode,
			"status_message": ttstr(u.szStatusMsg),
			"user_type": u.uUserType,
			"ip_address": ttstr(u.szIPAddress),
			"client_name": ttstr(u.szClientName),
			"user_data": u.nUserData,
			"version": u.uVersion,
			"local_subscriptions": u.uLocalSubscriptions,
			"peer_subscriptions": u.uPeerSubscriptions,
			"user_state": u.uUserState,
			"media_storage_dir": ttstr(u.szMediaStorageDir),
			"volume_voice": u.nVolumeVoice,
			"volume_mediafile": u.nVolumeMediaFile,
			"sound_position_voice": list(u.soundPositionVoice),
			"sound_position_mediafile": list(u.soundPositionMediaFile),
			"stereo_playback_voice": [bool(x) for x in u.stereoPlaybackVoice],
			"stereo_playback_mediafile": [bool(x) for x in u.stereoPlaybackMediaFile],
			"buffer_msec_voice": u.nBufferMSecVoice,
			"buffer_msec_mediafile": u.nBufferMSecMediaFile,
			"active_adaptive_delay_msec": u.nActiveAdaptiveDelayMSec,
		}

	def _parse_user(self, u):
		if not u: return {}
		return {
			"user_id": u.nUserID,
			"username": ttstr(u.szUsername),
			"nickname": ttstr(u.szNickname),
			"channel_id": u.nChannelID,
			"status_mode": u.nStatusMode,
			"status_msg": ttstr(u.szStatusMsg),
			"user_type": u.uUserType,
			"ip": ttstr(u.szIPAddress),
			"client": ttstr(u.szClientName),
			# بیت‌های خامِ UserState، برای مصرف‌کننده‌های آینده.
			"user_state": u.uUserState,
			# از پیش دیکد شده (USERSTATE_VOICE) تا core/voice_search.py و
			# بقیه‌ی core/ لازم نباشه enum های خودِ SDK رو import کنن -- اون
			# ماژول‌ها نباید به بارگذاریِ DLL تیم‌تاک وابسته بشن (تست‌های
			# آفلاین بدونِ DLL باید بتونن import و اجراش کنن).
			"talking": bool(u.uUserState & UserState.USERSTATE_VOICE),
		}

	def collect_full_message(self, msg):
		text = ttstr(msg.textmessage.szMessage)
		# رویدادهای صدا (فقط موقع جستجوی صوتی) ممکنه بین تکه‌های یه پیام
		# بلند برسن؛ اون‌ها پردازش و رد می‌شن، نه این‌که union شون به‌عنوان
		# متن خونده بشه. سقف فقط محافظ حلقه‌ی بی‌پایانه -- اگه رد بشه، به‌جای
		# خوندنِ حافظه‌ی یه بلوکِ صدا به‌عنوانِ textmessage (union مشترکه، پس
		# داده‌ش کاملاً بی‌معنی می‌شد)، پیامِ ناقص همون‌جا برمی‌گرده.
		skipped_audio = 0
		while msg.textmessage.bMore:
			next_msg = self.tt.getMessage(100)
			if not next_msg:
				break
			if next_msg.nClientEvent == ClientEvent.CLIENTEVENT_USER_AUDIOBLOCK:
				if skipped_audio >= 500:
					break
				skipped_audio += 1
				self._handle_audio_block_event(next_msg)
				continue
			text += ttstr(next_msg.textmessage.szMessage)
			msg = next_msg
		return text

	def set_server(self, host, tcp_port, udp_port, local_tcp=0, local_udp=0, encrypted=False):
		self.server_info = {
			"host": ttstr(host),
			"tcp": tcp_port,
			"udp": udp_port,
			"local_tcp": local_tcp,
			"local_udp": local_udp,
			"encrypted": encrypted
		}
		return self

	def _wait_for_event(self, event, timeout_ms=3000):
		"""Wait for a specific event with timeout. Sleep 10ms between checks to avoid busy-wait."""
		end = time.time() + timeout_ms / 1000
		while time.time() < end:
			msg = self.tt.getMessage(100)
			if msg:
				if msg.nClientEvent == ClientEvent.CLIENTEVENT_USER_AUDIOBLOCK and event != msg.nClientEvent:
					self._handle_audio_block_event(msg)
					continue
				self.event_buffer.append(msg)
				if msg.nClientEvent == event:
					return True, msg
				if msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_ERROR:
					err = msg.clienterrormsg
					raise TeamTalkCommandError(err.nErrorNo, ttstr(err.szErrorMsg))
				self._pending_events.append(msg)
			else:
				# No message available, sleep briefly to avoid CPU waste during polling
				time.sleep(0.01)
		return False, TTMessage()

	def connect(self):
		ok = self.tt.connect(
			self.server_info["host"],
			self.server_info["tcp"],
			self.server_info["udp"],
			self.server_info["local_tcp"],
			self.server_info["local_udp"],
			self.server_info["encrypted"]
		)
		if not ok:
			raise Exception("Connection failed")

		ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CON_SUCCESS, 5000)
		if not ok:
			raise Exception("Connection not successful")
		return self

	def disconnect(self):
		self.tt.disconnect()

	def login(self, nickname, username, password, clientname):
		self.tt.doLogin(ttstr(nickname), ttstr(username), ttstr(password), ttstr(clientname))
		ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN, 5000)
		if not ok:
			raise Exception("Login failed")
		return self

	def join(self, channel_id, password=""):
		if not self.tt.doJoinChannelByID(channel_id, ttstr(password)):
			return False
		ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SUCCESS, 5000)
		if not ok:
			return False
		return self

	EVENT_MAP = {
		ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG: {
			TextMsgType.MSGTYPE_USER: "user_msg",
			TextMsgType.MSGTYPE_CHANNEL: "channel_msg",
			TextMsgType.MSGTYPE_BROADCAST: "broadcast_msg",
			TextMsgType.MSGTYPE_CUSTOM: "custom_msg",
		},
		ClientEvent.CLIENTEVENT_CMD_USER_JOINED: "user_join",
		ClientEvent.CLIENTEVENT_CMD_USER_LEFT: "user_left",
		ClientEvent.CLIENTEVENT_CMD_USER_UPDATE: "user_updated",
		ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN: "user_logged_in",
		ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT: "user_logged_out",
		ClientEvent.CLIENTEVENT_USER_STATECHANGE: "user_state_changed",
		# params: {user_id, sample_rate, channels, pcm (bytes), stream_type, stream_id}
		# -- یه بار برای هر بلوک؛ بلوک قبل از رسیدن به subscriber کپی و آزاد شده.
		ClientEvent.CLIENTEVENT_USER_AUDIOBLOCK: "user_audio_block",

		ClientEvent.CLIENTEVENT_FILETRANSFER: "file_transfer",
		ClientEvent.CLIENTEVENT_CMD_FILE_NEW: "file_added",
		ClientEvent.CLIENTEVENT_CMD_FILE_REMOVE: "file_removed",

		ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW: "channel_new",
		ClientEvent.CLIENTEVENT_CMD_CHANNEL_UPDATE: "channel_updated",
		ClientEvent.CLIENTEVENT_CMD_CHANNEL_REMOVE: "channel_removed",

		ClientEvent.CLIENTEVENT_CMD_SERVER_UPDATE: "server_updated",

		ClientEvent.CLIENTEVENT_CMD_USERACCOUNT_NEW: "user_account_created",
		ClientEvent.CLIENTEVENT_CMD_USERACCOUNT_REMOVE: "user_account_removed",

		ClientEvent.CLIENTEVENT_SOUNDDEVICE_ADDED: "sound_device_added",
		ClientEvent.CLIENTEVENT_SOUNDDEVICE_REMOVED: "sound_device_removed",
		ClientEvent.CLIENTEVENT_SOUNDDEVICE_UNPLUGGED: "sound_device_unplugged",

		ClientEvent.CLIENTEVENT_CON_LOST: "connection_lost",
		ClientEvent.CLIENTEVENT_CON_FAILED: "connection_failed",

		ClientEvent.CLIENTEVENT_CMD_MYSELF_KICKED: "kicked",
		ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDOUT: "logged_out"
	}

	def subscribe(self, event_name):
		def decorator(func):
			self.subscribers[event_name].append(func)
			return func
		return decorator

	def safe_user_info(self, user_id):
		"""
		مثل get_user_info ولی هیچ‌وقت exception نمی‌ده. اگه کاربر همون لحظه
		از سرور رفته باشه (که موقع پردازش پیامِ خودش کاملاً ممکنه)، به‌جای
		کرش، یه dict حداقلی با همون آیدی برمی‌گردونه.
		"""
		try:
			return self.get_user_info(user_id)
		except Exception:
			return {
				"user_id": user_id,
				"username": "",
				"nickname": "",
				"channel_id": 0,
			}

	def handle_messages(self, timeout=50):
		# اول رویدادهایی که موقع انتظار برای جواب یه دستور کنار گذاشته شدن
		# (تا گم نشن)، بعد صف واقعی SDK.
		if self._pending_events:
			msg = self._pending_events.popleft()
		else:
			msg = self.tt.getMessage(timeout)
		if not msg: return
		try:
			self._dispatch_message(msg)
		except Exception:
			# هیچ خطایی موقع پارس یه رویداد نباید حلقه‌ی اصلی ربات رو
			# بکشه؛ قبلاً مثلاً get_user_info روی کاربری که همون لحظه رفته
			# بود raise می‌کرد و کل ربات می‌مرد.
			try:
				from core import logging_setup
				logging_setup.log_exception("parsing a TeamTalk event")
			except Exception:
				pass

	def _dispatch_message(self, msg):
		evt = msg.nClientEvent
		name = None
		params = {}

		if evt == ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG:
			mt = msg.textmessage.nMsgType
			name = self.EVENT_MAP[ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG].get(mt, "custom_msg")
			params = {
				"user": self.safe_user_info(msg.textmessage.nFromUserID),
				"channel_id": msg.textmessage.nChannelID,
				"message": self.collect_full_message(msg)
			}

		elif evt in (ClientEvent.CLIENTEVENT_CMD_USER_JOINED, ClientEvent.CLIENTEVENT_CMD_USER_LEFT):
			name = self.EVENT_MAP[evt]
			u = msg.user
			if not u.nUserID and msg.nSource:
				temp_u = self.tt.getUser(msg.nSource)
				if temp_u: u = temp_u

			params = {
				"user": self._parse_user(u),
				"channel_id": msg.nSource if evt == ClientEvent.CLIENTEVENT_CMD_USER_LEFT else u.nChannelID
			}

		elif evt == ClientEvent.CLIENTEVENT_CMD_FILE_NEW:
			name = self.EVENT_MAP[evt]
			rf = msg.remotefile
			params = {
				"channel_id": rf.nChannelID, "file_id": rf.nFileID,
				"filename": ttstr(rf.szFileName), "size": rf.nFileSize,
				"uploader": ttstr(rf.szUsername)
			}

		elif evt == ClientEvent.CLIENTEVENT_CMD_FILE_REMOVE:
			name = self.EVENT_MAP[evt]
			rf = msg.remotefile
			params = {
				"channel_id": rf.nChannelID, "file_id": rf.nFileID,
				"filename": ttstr(rf.szFileName)
			}

		elif evt == ClientEvent.CLIENTEVENT_FILETRANSFER:
			name = self.EVENT_MAP[evt]
			ft = msg.filetransfer
			params = {
				"transfer_id": ft.nTransferID, "channel_id": ft.nChannelID,
				"status": ft.nStatus, "filename": ttstr(ft.szRemoteFileName),
				"size": ft.nFileSize, "transferred": ft.nTransferred,
				"inbound": bool(ft.bInbound)
			}

		elif evt == ClientEvent.CLIENTEVENT_CON_LOST:
			name = self.EVENT_MAP[evt]
			params = {"reason": "connection_lost"}

		elif evt == ClientEvent.CLIENTEVENT_CON_FAILED:
			name = self.EVENT_MAP[evt]
			params = {"reason": "connection_failed"}

		elif evt == ClientEvent.CLIENTEVENT_CMD_MYSELF_KICKED:
			name = self.EVENT_MAP[evt]
			params = {"channel_id": msg.nSource}

		elif evt == ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDOUT:
			name = self.EVENT_MAP[evt]
			params = {}

		elif evt == ClientEvent.CLIENTEVENT_CMD_USER_UPDATE:
			name = self.EVENT_MAP[evt]
			params = {"user": self._parse_user(msg.user)}

		elif evt in (ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN, ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT):
			name = self.EVENT_MAP[evt]
			params = {"user": self._parse_user(msg.user)}

		elif evt == ClientEvent.CLIENTEVENT_USER_STATECHANGE:
			name = self.EVENT_MAP[evt]
			params = {"user": self._parse_user(msg.user)}

		elif evt == ClientEvent.CLIENTEVENT_USER_AUDIOBLOCK:
			# حتی بدون subscriber هم بلوک‌ها برداشته و آزاد می‌شن، تا حافظه‌ی
			# SDK پر نمونه.
			name = self.EVENT_MAP[evt]
			for block in self.drain_audio_blocks(msg.nSource, msg.nStreamType):
				self._notify(name, block, msg)
			return

		elif evt in (ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW, ClientEvent.CLIENTEVENT_CMD_CHANNEL_UPDATE,
		             ClientEvent.CLIENTEVENT_CMD_CHANNEL_REMOVE):
			name = self.EVENT_MAP[evt]
			params = {"channel": self._parse_channel(msg.channel)}

		elif evt == ClientEvent.CLIENTEVENT_CMD_SERVER_UPDATE:
			name = self.EVENT_MAP[evt]
			sp = msg.serverproperties
			params = {"name": ttstr(sp.szServerName), "motd": ttstr(sp.szMOTD), "max_users": sp.nMaxUsers}

		elif evt in (ClientEvent.CLIENTEVENT_CMD_USERACCOUNT_NEW, ClientEvent.CLIENTEVENT_CMD_USERACCOUNT_REMOVE):
			name = self.EVENT_MAP[evt]
			params = {"account": self._parse_user_account(msg.useraccount)}

		elif evt in (ClientEvent.CLIENTEVENT_SOUNDDEVICE_ADDED, ClientEvent.CLIENTEVENT_SOUNDDEVICE_REMOVED,
		             ClientEvent.CLIENTEVENT_SOUNDDEVICE_UNPLUGGED):
			name = self.EVENT_MAP[evt]
			params = {"device_id": msg.sounddevice.nDeviceID, "name": ttstr(msg.sounddevice.szDeviceName)}

		if name:
			self._notify(name, params, msg)

	def _notify(self, name, params, msg):
		if name in self.subscribers:
			data = {"event": name, "params": params, "raw": msg}
			for func in list(self.subscribers[name]):
				try:
					func(data)
				except Exception:
					try:
						from core import logging_setup
						logging_setup.log_exception(f"handling '{name}' event")
					except Exception:
						import traceback
						traceback.print_exc()

	def my_id(self):
		with self._tt_lock:
			return self.tt.getMyUserID()

	def get_channel_users(self, channel_id=None, exclude_self=True):
		"""لیست کاربرهای یه کانال رو برمی‌گردونه (پیش‌فرض: کانال فعلی خودمون)."""
		if channel_id is None:
			channel_id = self.get_user_info()["channel_id"]
		users = [self._parse_user(u) for u in self.tt.getChannelUsers(channel_id)]
		if exclude_self:
			my_id = self.my_id()
			users = [u for u in users if u.get("user_id") != my_id]
		return users

	def _check_rate_limit(self):
		"""
		True یعنی مجازیم بفرستیم. اگه توی MSG_RATE_LIMIT_WINDOW ثانیه‌ی
		اخیر بیش از MSG_RATE_LIMIT_MAX پیام فرستاده باشیم، False برمی‌گردونه
		(caller باید throttle/queue کنه) -- جلوگیری از flood کردن یه کاربر
		یا کانال (مثلاً به‌خاطر یه اشتباه توی یه لوپ).
		"""
		now = time.time()
		with self._msg_rate_lock:
			while self._msg_send_times and now - self._msg_send_times[0] > self.MSG_RATE_LIMIT_WINDOW:
				self._msg_send_times.popleft()
			if len(self._msg_send_times) >= self.MSG_RATE_LIMIT_MAX:
				return False
			self._msg_send_times.append(now)
			return True

	def _send_one_with_retry(self, msg):
		"""یه TextMessage رو با چند بار تلاش (backoff نمایی) می‌فرسته."""
		delay = self.MSG_RETRY_BACKOFF
		for attempt in range(self.MSG_MAX_RETRIES):
			if self.tt.doTextMessage(msg):
				return True
			if attempt < self.MSG_MAX_RETRIES - 1:
				time.sleep(delay)
				delay *= 2
		return False

	def _send_chunks(self, msg_type, target_id, content, queue_on_failure=True):
		if not self._check_rate_limit():
			logging_setup.log_debug(f"[ttbot] rate-limited a message to target {target_id}, queueing")
			if queue_on_failure:
				self._queue_failed_message(msg_type, target_id, content)
			raise Exception("Rate limit exceeded, message queued for retry")

		with self._send_lock:
			kwargs = {"nToUserID": target_id} if msg_type == TextMsgType.MSGTYPE_USER else {"nChannelID": target_id}
			messages = buildTextMessage(content, nMsgType=msg_type, **kwargs)
			for i, msg in enumerate(messages):
				ok = self._send_one_with_retry(msg)
				if not ok:
					if queue_on_failure:
						self._queue_failed_message(msg_type, target_id, content)
					raise Exception("Message sending failed after retries")
				# فاصله‌ی کوچیک بین تکه‌های یک پیام طولانی (bMore) تا سرور/کلاینت
				# گیرنده رو با یه رگبار پشت‌سرهم پیام غرق نکنیم.
				if i < len(messages) - 1:
					time.sleep(self.MSG_CHUNK_DELAY)
		return True

	def _queue_failed_message(self, msg_type, target_id, content):
		"""پیام ناموفق رو برای retry پس‌زمینه صف می‌کنه و worker رو (اگه لازم بود) استارت می‌کنه."""
		self._failed_messages.append({
			"msg_type": msg_type,
			"target_id": target_id,
			"content": content,
			"queued_at": time.time(),
		})
		self._ensure_retry_worker()

	def _ensure_retry_worker(self):
		with self._retry_worker_lock:
			if self._retry_worker_running:
				return
			self._retry_worker_running = True
			threading.Thread(target=self._retry_worker_loop, daemon=True, name="tt-msg-retry").start()

	def _retry_worker_loop(self):
		"""
		هر چند ثانیه یه‌بار صف پیام‌های ناموفق رو خالی می‌کنه. پیام‌های
		قدیمی‌تر از MSG_QUEUE_MAX_AGE (بی‌فایده شدن، مثلاً کاربر رفته) دور
		ریخته می‌شن. وقتی صف خالی شد، خودش تموم می‌شه (دوباره با اولین
		شکست، از نو استارت می‌شه).
		"""
		try:
			while True:
				time.sleep(5)
				if not self._failed_messages:
					return
				item = self._failed_messages.popleft()
				if time.time() - item["queued_at"] > self.MSG_QUEUE_MAX_AGE:
					logging_setup.log_debug(f"[ttbot] dropping stale queued message to {item['target_id']}")
					continue
				try:
					self._send_chunks(item["msg_type"], item["target_id"], item["content"], queue_on_failure=False)
				except Exception:
					if time.time() - item["queued_at"] <= self.MSG_QUEUE_MAX_AGE:
						self._failed_messages.append(item)
		finally:
			with self._retry_worker_lock:
				self._retry_worker_running = False

	def user_message(self, user_id, content):
		return self._send_chunks(TextMsgType.MSGTYPE_USER, user_id, content)

	def channel_message(self, content, channel_id=None):
		if channel_id is None:
			channel_id = self.get_user_info()["channel_id"]
		return self._send_chunks(TextMsgType.MSGTYPE_CHANNEL, channel_id, content)

	def broadcast_message(self, content):
		"""پیام سراسری به تمام کاربران سرور (نیاز به دسترسی ادمین روی سرور دارد)."""
		return self._send_chunks(TextMsgType.MSGTYPE_BROADCAST, 0, content)

	def smart_message(self, uid, content, channel_id=None, prefer_channel=False, allow_channel=True):
		"""
		انتخاب خودکار مقصد پیام:
		  - prefer_channel=True و allow_channel=True: اول تلاش برای کانال؛
		    اگه fail بشه (مثلاً کاربر دیگه اونجا نیست یا پیام کانال قطعه)،
		    خودکار به‌جاش private برای uid می‌فرسته (بدون گم‌شدن پیام).
		  - در غیر این صورت: مستقیم private.
		این چیزیه که همه‌ی جاهایی که الان دستی تصمیم می‌گیرن private بفرستن
		یا channel_broadcast صدا بزنن، می‌تونن به‌جاش صدا بزنن.
		"""
		if prefer_channel and allow_channel:
			try:
				return self.channel_message(content, channel_id)
			except Exception:
				logging_setup.log_debug(f"[ttbot] smart_message: channel send failed, falling back to private for uid={uid}")
		return self.user_message(uid, content)

	def set_microphone(self, status: bool):
		ok = self.tt.enableVoiceTransmission(status)
		if not ok:
			raise Exception("Microphone status change failed")
		if status==True:
			self.mic_open = True
		else:
			self.mic_open = False

		return True

	def mike_status(self):
		return self.mic_open

	def get_input_devices(self):
		devices = []
		sound_devices = self.tt.getSoundDevices()
		for dev in sound_devices:
			devices.append((dev.nDeviceID, ttstr(dev.szDeviceName)))
		return devices

	def set_input_device(self, device_id):
		ok = self.tt.initSoundInputDevice(device_id)
		if not ok:
			raise Exception("Input device setup failed")
		return True

	def set_status(self, mode=0x1000, message=""):
		# پیش‌فرضِ mode خنثی (0x1000) است، نه مرد (۰) -- core/status_line.py
		# تنها صداکننده‌ست و همیشه صریح می‌فرسته، ولی اگه یه‌روز جای دیگه‌ای
		# بدون mode صداش زد، نباید بی‌سروصدا جنسیتِ مرد بگیره (E3).
		self.tt.doChangeStatus(mode, ttstr(message))
		return True

	def set_name(self, new_name: str):
		"""
		تغییر nickname کاربر فعلی.
		"""
		ok = self.tt.doChangeNickname(ttstr(new_name))
		if ok <= 0:
			raise Exception(f"Could not change nickname: {ok}")
		return True

	def upload_file(self, filepath, chanid=None):
		with self._tt_lock:
			if chanid is None:
				chanid = self.get_user_info()["channel_id"]

			transfer_id = self.tt.doSendFile(chanid, ttstr(filepath))
			if transfer_id <= 0:
				raise Exception(f"File upload could not be started: {transfer_id}")
			return transfer_id

	def list_channel_files(self, channel_id=None):
		"""
		گرفتن لیست فایل‌های موجود در یک کانال.
		اگر channel_id داده نشود، کانال فعلی کاربر استفاده می‌شود.
		"""
		with self._tt_lock:
			if channel_id is None:
				channel_id = self.get_user_info()["channel_id"]

			files = self.tt.getChannelFiles(channel_id)
			result = []
			for f in files:
				result.append({
					"file_id": f.nFileID,
					"channel_id": f.nChannelID,
					"filename": ttstr(f.szFileName),
					"size": f.nFileSize,
					"uploader": ttstr(f.szUsername),
					"upload_time": ttstr(f.szUploadTime),
				})
			return result

	def delete_file(self, channel_id: int | None = None, file: int | str | None = None):
		"""
		حذف فایل از کانال. ترتیب ورودی: channel_id, file
		- اگر channel_id داده نشود، کانال فعلی ربات استفاده می‌شود.
		- file می‌تواند file_id (int) یا filename (str) باشد.
		"""
		with self._tt_lock:
			if channel_id is None:
				channel_id = self.get_user_info()["channel_id"]
			if file is None:
				return {"success": False, "error": "file is required (id or name)"}

			if isinstance(file, int):
				file_id = file
			else:
				files = self.list_channel_files(channel_id)
				match = next((f for f in files if f["filename"] == file), None)
				if not match:
					return {"success": False, "error": f"File '{file}' not found in channel {channel_id}"}
				file_id = match["file_id"]

			ok = self.tt.doDeleteFile(channel_id, file_id)
			return {"success": bool(ok), "channel_id": channel_id, "file_id": file_id}

	def download_file(self, file_id, local_path, channel_id=None):
		"""
		دانلود یه فایل از کانال به مسیر محلی local_path. file_id از
		list_channel_files می‌گیری. مثل upload_file، فقط انتقال رو شروع
		می‌کنه و transfer_id برمی‌گردونه (پیشرفت/تکمیل از طریق رویدادهای
		FILETRANSFER قابل‌پیگیریه، نه اینجا).
		"""
		with self._tt_lock:
			if channel_id is None:
				channel_id = self.get_user_info()["channel_id"]

			transfer_id = self.tt.doRecvFile(channel_id, file_id, ttstr(local_path))
			if transfer_id <= 0:
				raise Exception(f"File download could not be started: {transfer_id}")
			return transfer_id

	def _parse_channel(self, c):
		if not c:
			return {}
		return {
			"channel_id": c.nChannelID,
			"parent_id": c.nParentID,
			"name": ttstr(c.szName),
			"topic": ttstr(c.szTopic),
			"has_password": bool(c.bPassword),
			"channel_type": c.uChannelType,
			"max_users": c.nMaxUsers,
			"disk_quota": c.nDiskQuota,
			"user_data": c.nUserData,
		}

	def get_root_channel_id(self):
		return self.tt.getRootChannelID()

	def get_my_channel_id(self):
		return self.tt.getMyChannelID()

	def get_channel(self, channel_id):
		"""اطلاعات یک کانال با آیدی‌اش. اگه پیدا نشه Exception می‌ده."""
		c = self.tt.getChannel(channel_id)
		if not c or not c.nChannelID:
			raise Exception(f"Channel {channel_id} not found")
		return self._parse_channel(c)

	def get_channel_path(self, channel_id):
		"""مسیر متنی کانال، مثلاً '/General/Music'."""
		return ttstr(self.tt.getChannelPath(channel_id))

	def get_channel_id_from_path(self, path):
		"""عکسِ get_channel_path: از روی مسیر متنی، آیدی کانال رو برمی‌گردونه (0 یعنی پیدا نشد)."""
		return self.tt.getChannelIDFromPath(ttstr(path))

	def list_channels(self):
		"""همه‌ی کانال‌های سرور (مسطح، نه درختی) رو برمی‌گردونه."""
		return [self._parse_channel(c) for c in self.tt.getServerChannels()]

	def create_channel(self, name, parent_id=None, password="", topic="", max_users=0,
	                    channel_type=ChannelType.CHANNEL_DEFAULT, op_password=""):
		"""
		یه کانال جدید می‌سازه (اگه parent_id ندی، زیر روت ساخته می‌شه).
		موفقیت رو صبر می‌کنه (تا CLIENTEVENT_CMD_SUCCESS)، وگرنه Exception می‌ده.
		آیدی کانال تازه‌ساخته‌شده رو برمی‌گردونه.
		"""
		ch = Channel()
		ch.nParentID = parent_id if parent_id is not None else self.tt.getRootChannelID()
		ch.nChannelID = 0
		ch.szName = ttstr(name)
		ch.szTopic = ttstr(topic)
		ch.szPassword = ttstr(password)
		ch.szOpPassword = ttstr(op_password)
		ch.uChannelType = channel_type
		ch.nMaxUsers = max_users

		cmd_id = self.tt.doMakeChannel(ch)
		if cmd_id <= 0:
			raise Exception(f"Could not create channel: {cmd_id}")
		ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SUCCESS, 5000)
		if not ok:
			raise Exception(f"Channel creation not confirmed by server: '{name}'")
		return self.tt.getChannelIDFromPath(ttstr(self._join_path(parent_id, name)))

	def _join_path(self, parent_id, name):
		"""مسیر کامل یه زیرکانال رو از روی مسیر والدش می‌سازه (کمک برای create_channel)."""
		if parent_id is None or parent_id == self.tt.getRootChannelID():
			return f"/{name}"
		parent_path = ttstr(self.tt.getChannelPath(parent_id))
		return f"{parent_path}/{name}"

	def update_channel(self, channel_id, name=None, password=None, topic=None, max_users=None,
	                    channel_type=None, op_password=None):
		"""
		فقط فیلدهایی که مقدار بدی عوض می‌شن (بقیه از مقدار فعلی کانال خونده می‌شن).
		منتظر تأیید سرور می‌مونه، وگرنه Exception می‌ده.
		"""
		ch = self.tt.getChannel(channel_id)
		if not ch or not ch.nChannelID:
			raise Exception(f"Channel {channel_id} not found")
		if name is not None:
			ch.szName = ttstr(name)
		if password is not None:
			ch.szPassword = ttstr(password)
		if topic is not None:
			ch.szTopic = ttstr(topic)
		if max_users is not None:
			ch.nMaxUsers = max_users
		if channel_type is not None:
			ch.uChannelType = channel_type
		if op_password is not None:
			ch.szOpPassword = ttstr(op_password)

		cmd_id = self.tt.doUpdateChannel(ch)
		if cmd_id <= 0:
			raise Exception(f"Could not update channel {channel_id}: {cmd_id}")
		ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SUCCESS, 5000)
		if not ok:
			raise Exception(f"Channel update not confirmed by server: {channel_id}")
		return True

	def remove_channel(self, channel_id):
		"""حذف کامل یه کانال (باید خالی باشه). منتظر تأیید سرور می‌مونه."""
		cmd_id = self.tt.doRemoveChannel(channel_id)
		if cmd_id <= 0:
			raise Exception(f"Could not remove channel {channel_id}: {cmd_id}")
		ok, _ = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SUCCESS, 5000)
		if not ok:
			raise Exception(f"Channel removal not confirmed by server: {channel_id}")
		return True

	def leave_channel(self):
		"""از کانال فعلی خارج می‌شه (بدون قطع کامل اتصال از سرور)."""
		self.tt.doLeaveChannel()
		return True

	def kick_user(self, user_id, channel_id=0):
		"""
		کاربر رو از کانال کیک می‌کنه. channel_id=0 یعنی از کانال فعلیش
		(هرجا که هست) کیک بشه؛ برای کیک از کل سرور هم channel_id=0 با یه
		user_id معتبر کافیه (طبق رفتار خودِ پروتکل تیم‌تاک).
		"""
		ok = self.tt.doKickUser(user_id, channel_id)
		if ok <= 0:
			raise Exception(f"Could not kick user {user_id}: {ok}")
		return True

	def move_user(self, user_id, target_channel_id):
		"""کاربر رو به یه کانال دیگه منتقل می‌کنه (نیاز به دسترسی MOVE_USERS داره)."""
		ok = self.tt.doMoveUser(user_id, target_channel_id)
		if ok <= 0:
			raise Exception(f"Could not move user {user_id} to channel {target_channel_id}: {ok}")
		return True

	def ban_user(self, user_id, channel_id=0):
		"""بن کردن کاربر از یه کانال (0 = کانال فعلیش)."""
		ok = self.tt.doBanUser(user_id, channel_id)
		if ok <= 0:
			raise Exception(f"Could not ban user {user_id}: {ok}")
		return True

	def ban_user_ex(self, user_id, ban_types=BanType.BANTYPE_IPADDR):
		"""بن کردن پیشرفته‌تر (با ترکیبی از BanType: IP/username/channel)."""
		ok = self.tt.doBanUserEx(user_id, ban_types)
		if ok <= 0:
			raise Exception(f"Could not ban user {user_id} (ex): {ok}")
		return True

	def unban_user(self, ip_address, channel_id=0):
		"""رفع بن با آدرس IP."""
		ok = self.tt.doUnBanUser(ttstr(ip_address), channel_id)
		if ok <= 0:
			raise Exception(f"Could not unban '{ip_address}': {ok}")
		return True

	def ban_ip_address(self, ip_address, channel_id=0):
		"""
		بن کردن مستقیم یه آدرس IP (بدون نیاز به این‌که کاربر الان آنلاین
		باشه) -- برخلاف ban_user که نیاز به user_id متصل داره.
		"""
		ok = self.tt.doBanIPAddress(ttstr(ip_address), channel_id)
		if ok <= 0:
			raise Exception(f"Could not ban IP '{ip_address}': {ok}")
		return True

	def save_server_config(self):
		"""به سرور می‌گه تنظیمات فعلی (کانال‌ها، اکانت‌ها، ...) رو روی دیسک ذخیره کنه."""
		ok = self.tt.doSaveConfig()
		if ok <= 0:
			raise Exception(f"Could not save server config: {ok}")
		return True

	def list_bans(self, channel_id=0, index=0, count=100):
		"""
		لیست کاربرهای بن‌شده رو برمی‌گردونه (channel_id=0 یعنی کل سرور).
		منتظر همه‌ی رویدادهای CMD_BANNEDUSER می‌مونه تا CMD_SUCCESS بیاد.
		"""
		cmd_id = self.tt.doListBans(channel_id, index, count)
		if cmd_id <= 0:
			raise Exception(f"Could not list bans: {cmd_id}")
		return self._collect_until_success(
			ClientEvent.CLIENTEVENT_CMD_BANNEDUSER,
			lambda msg: {
				"ip_address": ttstr(msg.banneduser.szIPAddress),
				"channel_path": ttstr(msg.banneduser.szChannelPath),
				"ban_time": ttstr(msg.banneduser.szBanTime),
				"nickname": ttstr(msg.banneduser.szNickname),
				"username": ttstr(msg.banneduser.szUsername),
				"ban_types": msg.banneduser.uBanTypes,
				"owner": ttstr(msg.banneduser.szOwner),
			},
		)

	def make_channel_operator(self, user_id, channel_id, make_operator=True, op_password=""):
		"""کاربر رو اپراتور یه کانال می‌کنه (یا از اپراتوری خارجش می‌کنه)."""
		if op_password:
			ok = self.tt.doChannelOpEx(user_id, channel_id, ttstr(op_password), make_operator)
		else:
			ok = self.tt.doChannelOp(user_id, channel_id, make_operator)
		if ok <= 0:
			raise Exception(f"Could not change operator status for user {user_id}: {ok}")
		return True

	def is_channel_operator(self, user_id, channel_id=None):
		"""
		True یعنی کاربر توی اون کانال (پیش‌فرض: کانال فعلی خودِ ربات)
		اپراتوره. برای سیستم سطح دسترسیِ دستورات (channel_operator tier)
		استفاده می‌شه؛ این وضعیت مستقیم از SDK خونده می‌شه، نه از کانفیگ ما.
		"""
		with self._tt_lock:
			if channel_id is None:
				channel_id = self.get_my_channel_id()
			return self.tt.isChannelOperator(user_id, channel_id)

	def _collect_until_success(self, collect_event, extract_fn, timeout_ms=5000):
		"""
		کمک‌تابع مشترک برای دستوراتی که چند رویداد پشت‌سرهم می‌فرستن (یکی
		به‌ازای هر آیتم) و در آخر با CMD_SUCCESS تموم می‌شن (مثل
		doListBans/doListUserAccounts). لیست extract_fn(msg) برای هر
		رویداد رو برمی‌گردونه.
		"""
		results = []
		end = time.time() + timeout_ms / 1000
		while time.time() < end:
			msg = self.tt.getMessage(100)
			if not msg:
				time.sleep(0.01)  # Avoid busy-wait when no messages
				continue
			if msg.nClientEvent == ClientEvent.CLIENTEVENT_USER_AUDIOBLOCK:
				self._handle_audio_block_event(msg)
				continue
			self.event_buffer.append(msg)
			if msg.nClientEvent == collect_event:
				results.append(extract_fn(msg))
			elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_SUCCESS:
				return results
			elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_ERROR:
				raise Exception("Server returned an error while listing.")
			else:
				self._pending_events.append(msg)
		return results

	def list_user_accounts(self, index=0, count=100):
		"""لیست اکانت‌های ثابت تعریف‌شده روی سرور (نیاز به دسترسی ادمین داره)."""
		cmd_id = self.tt.doListUserAccounts(index, count)
		if cmd_id <= 0:
			raise Exception(f"Could not list user accounts: {cmd_id}")
		return self._collect_until_success(
			ClientEvent.CLIENTEVENT_CMD_USERACCOUNT,
			lambda msg: self._parse_user_account(msg.useraccount),
		)

	def _parse_user_account(self, ua):
		return {
			"username": ttstr(ua.szUsername),
			"user_type": ua.uUserType,
			"user_rights": ua.uUserRights,
			"note": ttstr(ua.szNote),
			"init_channel": ttstr(ua.szInitChannel),
		}

	def create_user_account(self, username, password, user_type=UserType.USERTYPE_DEFAULT,
	                         user_rights=None, note="", init_channel=""):
		"""
		یه اکانت ثابت جدید روی سرور می‌سازه. user_rights رو اگه ندی، یه
		ست پیش‌فرض معقول (پیام دادن + صحبت + آپلود/دانلود) گذاشته می‌شه.
		"""
		if user_rights is None:
			user_rights = (
				UserRight.USERRIGHT_MULTI_LOGIN
				| UserRight.USERRIGHT_TRANSMIT_VOICE
				| UserRight.USERRIGHT_UPLOAD_FILES
				| UserRight.USERRIGHT_DOWNLOAD_FILES
			)
		ua = UserAccount()
		ua.szUsername = ttstr(username)
		ua.szPassword = ttstr(password)
		ua.uUserType = user_type
		ua.uUserRights = user_rights
		ua.szNote = ttstr(note)
		ua.szInitChannel = ttstr(init_channel)

		ok = self.tt.doNewUserAccount(ua)
		if ok <= 0:
			raise Exception(f"Could not create user account '{username}': {ok}")
		return True

	def delete_user_account(self, username):
		ok = self.tt.doDeleteUserAccount(ttstr(username))
		if ok <= 0:
			raise Exception(f"Could not delete user account '{username}': {ok}")
		return True

	def my_user_account(self):
		"""اکانتی که خودِ ربات باهاش لاگین کرده."""
		return self._parse_user_account(self.tt.getMyUserAccount())

	def get_user_by_username(self, username):
		"""پیدا کردن یه کاربرِ آنلاین با username (نه nickname). اگه آنلاین نباشه None."""
		u = self.tt.getUserByUsername(ttstr(username))
		if not u or not u.nUserID:
			return None
		return self._parse_user(u)

	def server_properties(self):
		sp = self.tt.getServerProperties()
		return {
			"name": ttstr(sp.szServerName),
			"motd": ttstr(sp.szMOTD),
			"max_users": sp.nMaxUsers,
			"tcp_port": sp.nTcpPort,
			"udp_port": sp.nUdpPort,
			"server_version": ttstr(sp.szServerVersion),
			"protocol_version": ttstr(sp.szServerProtocolVersion),
			# مدت‌زمانی (ثانیه) که سرور صبر می‌کنه قبل از این‌که یه کاربرِ
			# بی‌پاسخ (مثلاً به‌خاطر قطعی اینترنت) رو واقعاً از کانال حذف
			# کنه. تا وقتی این timeout نگذشته، get_channel_users همچنان
			# اون کاربر رو نشون می‌ده -- یعنی idle_channel auto-pause تا
			# اون‌موقع فکر می‌کنه کانال خالی نیست.
			"user_timeout": sp.nUserTimeout,
		}

	def update_server_properties(self, name=None, motd=None, max_users=None):
		"""
		تنظیمات سرور رو تغییر می‌ده (نیاز به دسترسی ادمین سرور داره، نه
		فقط ادمین کانال). فقط پارامترهایی که None نیستن عوض می‌شن؛ بقیه از
		مقدار فعلی سرور خونده می‌شن (SDK کل struct رو با هم می‌خواد، نه
		فقط فیلدهای تغییریافته).
		"""
		with self._tt_lock:
			sp = self.tt.getServerProperties()
			if name is not None:
				sp.szServerName = ttstr(name)
			if motd is not None:
				sp.szMOTD = ttstr(motd)
			if max_users is not None:
				sp.nMaxUsers = max_users
			ok = self.tt.doUpdateServer(sp)
			if ok <= 0:
				raise Exception(f"Could not update server properties: {ok}")
			return True

	def query_server_stats(self, timeout_ms=5000):
		"""آمار لحظه‌ای سرور (تعداد کاربر آنلاین، ترافیک و ...) رو می‌گیره."""
		cmd_id = self.tt.doQueryServerStats()
		if cmd_id <= 0:
			raise Exception(f"Could not query server stats: {cmd_id}")
		ok, msg = self._wait_for_event(ClientEvent.CLIENTEVENT_CMD_SERVERSTATISTICS, timeout_ms)
		if not ok:
			raise Exception("Server did not respond with statistics in time.")
		ss = msg.serverstatistics
		return {
			"users_served": ss.nUsersServed,
			"users_peak": ss.nUsersPeak,
			"total_bytes_tx": ss.nTotalBytesTX,
			"total_bytes_rx": ss.nTotalBytesRX,
			"uptime_msec": ss.nUptimeMSec,
		}

	def get_server_users(self):
		"""همه‌ی کاربرهای آنلاینِ سرور (نه فقط کانال فعلی)؛ نیاز به دسترسی VIEW_ALL_USERS داره."""
		return [self._parse_user(u) for u in self.tt.getServerUsers()]

	def logout(self):
		"""فقط لاگ‌اوت (بدون قطع کامل اتصال TCP)."""
		self.tt.doLogout()
		return True

	# --- audit قابلیت‌های خام (docs/TEAMTALK_WRAPPER.md) ---------------------
	#
	# متدهای این بخش تا امروز مصرف‌کننده‌ی مستقیمی توی core/commands نداشتن،
	# ولی چون core/teamtalk/TeamTalk5.py خودِ قابلیت رو داره، طبق سیاستِ «پوششِ کاملِ
	# SDK» اضافه شدن -- هرکدوم فقط یه لایه‌ی نازکِ تبدیل نوع روی متدِ متناظرِ
	# self.tt هستن، دقیقاً به همون سبکِ متدهای بالاتر.

	def default_sound_devices(self):
		"""آیدیِ دستگاهِ پیش‌فرضِ ورودی/خروجیِ سیستم‌عامل (نه دستگاه‌های خودِ تیم‌تاک)."""
		indev, outdev = self.tt.getDefaultSoundDevices()
		return int(indev), int(outdev)

	def set_encryption_context(self, cert_file, key_file, ca_file="", ca_dir="",
	                            verify_peer=False, verify_client_once=False, verify_depth=0):
		"""
		گواهی/کلیدِ TLS سفارشی رو قبل از connect() تنظیم می‌کنه. فقط وقتی لازمه
		که سرور از گواهیِ خودامضا یا CA سفارشی استفاده کنه.
		"""
		ctx = EncryptionContext()
		ctx.szCertificateFile = ttstr(cert_file)
		ctx.szPrivateKeyFile = ttstr(key_file)
		ctx.szCAFile = ttstr(ca_file)
		ctx.szCADir = ttstr(ca_dir)
		ctx.bVerifyPeer = bool(verify_peer)
		ctx.bVerifyClientOnce = bool(verify_client_once)
		ctx.nVerifyDepth = verify_depth
		return bool(self.tt.setEncryptionContext(ctx))

	def ping(self):
		"""یه پینگِ دستی به سرور (سرویسِ keep-alive خودش این کارو خودکار انجام می‌ده)."""
		return self.tt.doPing()

	def join_channel_struct(self, channel):
		"""
		مثلِ join()، ولی به‌جای channel_id از یه Channel struct کامل استفاده
		می‌کنه -- لازم وقتی سرور اجازه‌ی ساختنِ خودکارِ کانال موقعِ join رو داره.
		"""
		return self.tt.doJoinChannel(channel)

	def ban_full(self, ip_address="", channel_path="", nickname="", username="",
	             ban_types=BanType.BANTYPE_IPADDR, owner=""):
		"""
		بن‌کردن با یه رکوردِ کامل (IP + مسیرِ کانال + نامِ‌کاربری با هم)، به‌جای
		ban_user (نیازمندِ user_id آنلاین) یا ban_ip_address (فقط IP).
		"""
		bu = BannedUser()
		bu.szIPAddress = ttstr(ip_address)
		bu.szChannelPath = ttstr(channel_path)
		bu.szNickname = ttstr(nickname)
		bu.szUsername = ttstr(username)
		bu.uBanTypes = ban_types
		bu.szOwner = ttstr(owner)
		ok = self.tt.doBan(bu)
		if ok <= 0:
			raise Exception(f"Could not ban (full record): {ok}")
		return True

	def unban_full(self, ip_address="", channel_path="", nickname="", username="",
	               ban_types=BanType.BANTYPE_IPADDR, owner=""):
		"""عکسِ ban_full: رفعِ بن با همون رکوردِ کامل (نه فقط IP، مثلِ unban_user)."""
		bu = BannedUser()
		bu.szIPAddress = ttstr(ip_address)
		bu.szChannelPath = ttstr(channel_path)
		bu.szNickname = ttstr(nickname)
		bu.szUsername = ttstr(username)
		bu.uBanTypes = ban_types
		bu.szOwner = ttstr(owner)
		ok = self.tt.doUnbanUserEx(bu)
		if ok <= 0:
			raise Exception(f"Could not unban (full record): {ok}")
		return True

	def notify_quit(self):
		"""به سرور اطلاع می‌ده که کلاینت داره تمیز خارج می‌شه (قبلِ disconnect)."""
		self.tt.doQuit()
		return True

	def my_user_data(self):
		"""مقدارِ دلخواهِ nUserData که موقعِ لاگین/اکانت برای خودِ ربات تنظیم شده."""
		return self.tt.getMyUserData()

	def get_user_statistics(self, user_id):
		"""آمارِ جریان‌های صدا/تصویر/مدیای یه کاربر (پکت‌های رسیده/گم‌شده و ...)."""
		s = self.tt.getUserStatistics(user_id)
		return {
			"voice_packets_recv": s.nVoicePacketsRecv,
			"voice_packets_lost": s.nVoicePacketsLost,
			"video_capture_packets_recv": s.nVideoCapturePacketsRecv,
			"video_capture_frames_recv": s.nVideoCaptureFramesRecv,
			"video_capture_frames_lost": s.nVideoCaptureFramesLost,
			"video_capture_frames_dropped": s.nVideoCaptureFramesDropped,
			"media_file_audio_packets_recv": s.nMediaFileAudioPacketsRecv,
			"media_file_audio_packets_lost": s.nMediaFileAudioPacketsLost,
			"media_file_video_packets_recv": s.nMediaFileVideoPacketsRecv,
			"media_file_video_frames_recv": s.nMediaFileVideoFramesRecv,
			"media_file_video_frames_lost": s.nMediaFileVideoFramesLost,
			"media_file_video_frames_dropped": s.nMediaFileVideoFramesDropped,
		}

	def error_message(self, error_code):
		"""متنِ خوانا برای یه کدِ خطای ClientError.CMDERR_*/INTERR_*."""
		return ttstr(self.tt.getErrorMessage(error_code))

	def set_user_media_storage_dir(self, user_id, folder_path, filename_vars="",
	                                audio_format=AudioFileFormat.AFF_WAVE_FORMAT):
		"""
		مسیرِ ذخیره‌ی ضبطِ خودکارِ صدای این کاربر رو تنظیم می‌کنه. filename_vars
		الگوی اسمِ فایل رو مشخص می‌کنه (متغیرهاش توی مستندات SDK هستن).
		"""
		return bool(self.tt.setUserMediaStorageDir(user_id, ttstr(folder_path),
		                                            ttstr(filename_vars), audio_format))

	def set_user_stopped_playback_delay(self, user_id, stream_type, delay_msec):
		"""تأخیر قبل از این‌که پخشِ این کاربر «متوقف‌شده» حساب بشه (ضدِ قطع‌وصلیِ صدا)."""
		return bool(self.tt.setUserStoppedPlaybackDelay(user_id, stream_type, delay_msec))

	def start_streaming_media_file(self, path, video_codec=None):
		"""
		استریمِ یه فایلِ مدیا (صدا/تصویر) به کانالِ فعلی، برای همه‌ی کاربرهای اونجا.
		video_codec رو اگه ندی یعنی بدونِ ویدیو (NO_CODEC) -- کافیه برای رباتی
		که فقط صدا پخش می‌کنه.
		"""
		if video_codec is None:
			video_codec = VideoCodec()
			video_codec.nCodec = Codec.NO_CODEC
		return bool(self.tt.startStreamingMediaFileToChannel(ttstr(path), video_codec))

	def stop_streaming_media_file(self):
		"""توقفِ استریمِ فایلِ مدیایی که با start_streaming_media_file شروع شده."""
		return bool(self.tt.stopStreamingMediaFileToChannel())

	def init_local_playback(self, path, offset_msec=TT_MEDIAPLAYBACK_OFFSET_IGNORE, paused=False):
		"""
		پخشِ محلیِ یه فایلِ مدیا (فقط خودِ ربات می‌شنوه/می‌بینه، نه بقیه‌ی کانال --
		برای اون‌کار start_streaming_media_file لازمه). خروجی یه session id
		برای update_local_playback/stop_local_playback.
		"""
		mfp = MediaFilePlayback()
		mfp.uOffsetMSec = offset_msec
		mfp.bPaused = bool(paused)
		session_id = self.tt.initLocalPlayback(ttstr(path), mfp)
		if session_id <= 0:
			raise Exception(f"Could not start local playback of '{path}': {session_id}")
		return session_id

	def update_local_playback(self, session_id, offset_msec=TT_MEDIAPLAYBACK_OFFSET_IGNORE, paused=False):
		"""
		تغییرِ وضعیتِ پخشِ محلیِ در حال اجرا (session_id از init_local_playback).
		SDK هیچ getter ای برای وضعیتِ فعلی نداره، پس هر بار باید وضعیتِ کامل
		(offset + paused) رو صریح بدی؛ پیش‌فرضِ offset یعنی «دست‌نخورده بمونه».
		"""
		mfp = MediaFilePlayback()
		mfp.uOffsetMSec = offset_msec
		mfp.bPaused = bool(paused)
		return bool(self.tt.updateLocalPlayback(session_id, mfp))

	def stop_local_playback(self, session_id):
		"""توقفِ کاملِ یه session پخشِ محلی که با init_local_playback شروع شده."""
		return bool(self.tt.stopLocalPlayback(session_id))

	def enable_audio_block_event_ex(self, user_id, sample_rate, channels,
	                                 stream_type=StreamType.STREAMTYPE_VOICE, enable=True):
		"""
		مثلِ enable_audio_blocks، ولی صراحتاً sample rate/تعدادِ کاناله‌ی خروجیِ
		بلوک‌ها رو مشخص می‌کنه (SDK خودش resample/remix می‌کنه)، نه فرمتِ خامِ ورودی.
		"""
		fmt = AudioFormat()
		fmt.nAudioFmt = AudioFileFormat.AFF_CHANNELCODEC_FORMAT
		fmt.nSampleRate = sample_rate
		fmt.nChannels = channels
		return bool(self.tt.enableAudioBlockEventEx(user_id, stream_type, fmt, bool(enable)))

	def insert_audio_block(self, stream_id, sample_rate, channels, pcm_bytes,
	                        stream_types=StreamType.STREAMTYPE_VOICE, sample_index=0):
		"""
		عکسِ acquire_audio_block: یه بلوکِ PCM (16-bit) رو به SDK «تزریق» می‌کنه
		(مثلاً پخشِ صدای تولیدشده‌ی خودِ ربات، نه از یه فایلِ مدیا). بافر تا
		انتهای همین تماس زنده نگه داشته می‌شه -- SDK کپیِ خودش رو همون‌جا برمی‌داره.
		"""
		samples = len(pcm_bytes) // (2 * channels) if channels else 0
		buf = ctypes.create_string_buffer(pcm_bytes, len(pcm_bytes))
		block = AudioBlock()
		block.nStreamID = stream_id
		block.nSampleRate = sample_rate
		block.nChannels = channels
		block.lpRawAudio = ctypes.cast(buf, ctypes.c_void_p)
		block.nSamples = samples
		block.uSampleIndex = sample_index
		block.uStreamTypes = stream_types
		return bool(self.tt.insertAudioBlock(block))

	def media_file_info(self, path):
		"""
		اطلاعاتِ یه فایلِ مدیایِ محلی (بدونِ نیاز به اتصال). نکته: خودِ
		TeamTalk5.getMediaFileInfo پارامترِ self نداره (باگِ باندینگِ خامِ SDK)،
		پس صداکردنش از روی self.tt واقعاً کرش می‌کنه (self.tt به‌جایِ مسیر پاس
		می‌شه)؛ این‌جا با صداکردن از رویِ خودِ کلاس (نه نمونه) اون باگ دور زده می‌شه.
		"""
		info = type(self.tt).getMediaFileInfo(ttstr(path))
		return {
			"status": info.nStatus,
			"filename": ttstr(info.szFileName),
			"audio_sample_rate": info.audioFmt.nSampleRate,
			"audio_channels": info.audioFmt.nChannels,
			"video_width": info.videoFmt.nWidth,
			"video_height": info.videoFmt.nHeight,
			"duration_msec": info.uDurationMSec,
			"elapsed_msec": info.uElapsedMSec,
		}

	def sdk_version(self):
		"""نسخه‌ی DLL تیم‌تاکِ بارگذاری‌شده (بدونِ نیاز به نمونه/اتصال)."""
		return ttstr(getVersion())

	def set_license(self, name, key):
		"""
		ثبتِ لایسنسِ SDK (برای رفعِ حالتِ trial). معمولاً باید قبل از ساختنِ
		اولین TeamTalk() صدا زده بشه؛ روی نمونه‌ی موجود هم صداش بزنی بی‌ضرره.
		"""
		return bool(setLicense(ttstr(name), ttstr(key)))

	def rebuild_message(self, text_messages):
		"""
		عکسِ buildTextMessage: از یه لیستِ TextMessage (تکه‌های یه پیامِ بلند)
		متنِ کامل رو می‌سازه. پیام‌های زنده‌ی همینِ ربات از collect_full_message
		(که رویدادهای صدای وسطِ راه رو هم مدیریت می‌کنه) استفاده می‌کنن؛ این متد
		برای مصرف‌کننده‌های دیگه‌ست که خودشون لیستِ TextMessage جمع کرده‌ن.
		"""
		return rebuildTextMessage(text_messages)
