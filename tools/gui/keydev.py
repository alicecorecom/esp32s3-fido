# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""Talking to an esp32s3-fido key over its CCID (smart card) interface.

No Qt here. Every call opens its own connection and closes it again: the key
has one logical channel, so selecting the OATH applet on one connection would
silently deselect FIDO on another. Calls block (some wait for BOOT / touch);
the GUI runs them on one worker thread.
"""
import os
import struct
import sys
import time
from contextlib import contextmanager

from smartcard.System import readers

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fwupdate  # noqa: E402  (tools/fwupdate.py: update applet helpers)

from fido2.ctap2 import ClientPin, Config, CredentialManagement, Ctap2  # noqa: E402
from fido2.pcsc import CtapPcscDevice  # noqa: E402
from ykman.pcsc import ScardSmartCardConnection  # noqa: E402
from yubikit import oath as yoath  # noqa: E402
from yubikit.core import Tlv  # noqa: E402
from yubikit.management import ManagementSession  # noqa: E402
from yubikit.oath import OATH_TYPE, Credential, OathSession  # noqa: E402
from yubikit.yubiotp import SLOT, YubiOtpSession  # noqa: E402

UPDATE_AID = [0xF0] + list(b"espfido")
LED_ORDERS = fwupdate.LED_ORDERS
DEFAULT_LED_ORDER = fwupdate.DEFAULT_LED_ORDER


class KeyFailure(Exception):
    """An error to show to the user as it is."""


ADMIN_REQUIRED = ("Windows では、パスキー（FIDO）の管理に管理者権限が要ります。"
                  "「パスキー」タブの「管理者として起動し直す」を使ってください。")


def is_windows_non_admin():
    if os.name != "nt":
        return False
    try:
        import ctypes
        return not ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


READER_NAME = "ESP32-S3 FIDO2 Key"     # USB product string (patches/pico-fido-esp32s3.patch)


def list_keys():
    """Reader names of the plugged-in esp32s3-fido keys.

    By name only: the GUI polls this every few seconds, and talking to the
    card (even a SELECT) while the browser is in the middle of a FIDO request
    over HID can disturb that request.
    """
    return [str(r) for r in readers() if READER_NAME in str(r)]


def stage(flags):
    """The README's stage letter for the update applet's flags."""
    if flags & 4:
        return "C", "release（本番）"
    if flags & 2:
        return ("B+", "開発モードの暗号化＋セキュアブート") if flags & 1 else ("B", "開発モードの暗号化")
    return "A", "暗号化なし"


class Key:
    def __init__(self, reader_name):
        self.reader_name = reader_name

    # -- connections -------------------------------------------------------

    def _reader(self):
        for r in readers():
            if str(r) == self.reader_name:
                return r
        raise KeyFailure("キーが見つかりません（抜かれましたか？）")

    @contextmanager
    def _raw(self):
        c = self._reader().createConnection()
        c.connect()
        try:
            yield c
        finally:
            try:
                c.disconnect()
            except Exception:
                pass

    @contextmanager
    def _update_applet(self):
        with self._raw() as c:
            _, sw1, sw2 = c.transmit([0x00, 0xA4, 0x04, 0x00, len(UPDATE_AID)] + UPDATE_AID)
            if (sw1, sw2) != (0x90, 0x00):
                raise KeyFailure("更新用のアプレットが応答しません")
            yield c

    @contextmanager
    def _yk(self):
        with self._raw() as c:
            yield ScardSmartCardConnection(c)

    @contextmanager
    def _ctap(self):
        r = self._reader()
        try:
            d = CtapPcscDevice(r.createConnection(), str(r))
        except Exception as e:
            # Windows lets only elevated processes select the FIDO applet over PC/SC
            # (SCARD_E_NO_ACCESS), as it does for FIDO over HID; OATH / OTP / updates are fine
            if "0x80100027" in str(e):
                raise KeyFailure(ADMIN_REQUIRED)
            raise KeyFailure(f"FIDO の窓口に接続できません（{e}）")
        try:
            yield Ctap2(d)
        finally:
            try:
                d.close()
            except Exception:
                pass

    # -- firmware (update applet) -----------------------------------------

    def fw_info(self):
        with self._update_applet() as c:
            return fwupdate.info(c)

    def fw_update(self, img, progress):
        """Write `img` into the other slot; progress(done, total) is called from this thread."""
        with self._update_applet() as c:
            fwupdate.cmd(c, 0x10, struct.pack(">I", len(img)))      # waits for BOOT / touch
            try:
                for off in range(0, len(img), fwupdate.CHUNK):
                    fwupdate.cmd(c, 0x11, struct.pack(">I", off) + img[off:off + fwupdate.CHUNK])
                    progress(min(off + fwupdate.CHUNK, len(img)), len(img))
                fwupdate.cmd(c, 0x12)
            except Exception:
                try:
                    fwupdate.cmd(c, 0x13)
                except Exception:
                    pass
                raise
            fwupdate.cmd(c, 0x14)

    def fw_reboot(self):
        with self._update_applet() as c:
            fwupdate.cmd(c, 0x14)

    def led_order_set(self, order):
        """order: one of LED_ORDERS, or 'default'."""
        p1 = 0xFF if order == "default" or LED_ORDERS.index(order) == DEFAULT_LED_ORDER else LED_ORDERS.index(order)
        with self._update_applet() as c:
            fwupdate.set_led_order(c, p1)

    def led_blink(self, colour):
        """colour 0 red, 1 green, 2 blue (logical); blinks 3 times."""
        with self._update_applet() as c:
            _, sw1, sw2 = c.transmit([0x80, 0x21, colour + 1, 0x00])
            if (sw1, sw2) == (0x6D, 0x00):
                raise KeyFailure("このファームには LED の試験がありません（v0.1.2 以降）")

    # -- overview ----------------------------------------------------------

    def device_info(self):
        with self._yk() as yc:
            return ManagementSession(yc).read_device_info()

    def fido_info(self):
        with self._ctap() as ctap:
            info = ctap.info
            retries = None
            if info.options.get("clientPin"):
                retries = ClientPin(ctap).get_pin_retries()[0]
            return info, retries

    # -- FIDO ----------------------------------------------------------------

    def fido_set_pin(self, new):
        with self._ctap() as ctap:
            ClientPin(ctap).set_pin(new)

    def fido_change_pin(self, old, new):
        with self._ctap() as ctap:
            ClientPin(ctap).change_pin(old, new)

    def _token(self, ctap, pin, perm):
        cp = ClientPin(ctap)
        return cp.protocol, cp.get_pin_token(pin, perm)

    def fido_credentials(self, pin):
        """[(rp dict, [credential dicts])] and the metadata."""
        with self._ctap() as ctap:
            proto, tok = self._token(ctap, pin, ClientPin.PERMISSION.CREDENTIAL_MGMT)
            cm = CredentialManagement(ctap, proto, tok)
            meta = cm.get_metadata()
            out = []
            if meta.get(CredentialManagement.RESULT.EXISTING_CRED_COUNT, 0):
                for rp in cm.enumerate_rps():
                    creds = cm.enumerate_creds(rp[CredentialManagement.RESULT.RP_ID_HASH])
                    out.append((rp, creds))
            return out, meta

    def fido_delete_credential(self, pin, cred_id):
        with self._ctap() as ctap:
            proto, tok = self._token(ctap, pin, ClientPin.PERMISSION.CREDENTIAL_MGMT)
            CredentialManagement(ctap, proto, tok).delete_cred(cred_id)

    def fido_toggle_always_uv(self, pin):
        with self._ctap() as ctap:
            proto, tok = self._token(ctap, pin, ClientPin.PERMISSION.AUTHENTICATOR_CFG)
            Config(ctap, proto, tok).toggle_always_uv()

    def fido_set_min_pin(self, pin, length=None, force_change=False):
        with self._ctap() as ctap:
            proto, tok = self._token(ctap, pin, ClientPin.PERMISSION.AUTHENTICATOR_CFG)
            Config(ctap, proto, tok).set_min_pin_length(min_pin_length=length, force_change_pin=force_change)

    def fido_reset(self):
        with self._ctap() as ctap:
            ctap.reset()                                            # waits for BOOT / touch

    # -- OATH ----------------------------------------------------------------

    @contextmanager
    def _oath(self, password=None):
        with self._yk() as yc:
            s = OathSession(yc)
            if s.locked:
                if password is None:
                    raise KeyFailure("OATH_LOCKED")
                s.validate(s.derive_key(password))
            yield s

    def oath_locked(self):
        with self._yk() as yc:
            return OathSession(yc).locked

    def oath_codes(self, password=None):
        """[(Credential, Code|None, touch_required)] for all accounts."""
        with self._oath(password) as s:
            creds = s.list_credentials()
            codes = s.calculate_all()
            by_id = {c.id: (c, code) for c, code in codes.items()}
            out = []
            for c in creds:
                cc, code = by_id.get(c.id, (c, None))
                out.append((c, code, bool(cc.touch_required)))
            return out

    def oath_calculate(self, cred, password=None):
        with self._oath(password) as s:
            return s.calculate_code(cred)

    def oath_put(self, data, touch, password=None):
        """OathSession.put_credential with the touch property as a TLV pico-fido reads (see oath.py)."""
        with self._oath(password) as s:
            secret = yoath._hmac_shorten_key(data.secret, data.hash_algorithm).ljust(yoath.HMAC_MINIMUM_KEY_SIZE, b"\0")
            body = Tlv(yoath.TAG_NAME, data.get_id()) + Tlv(
                yoath.TAG_KEY, struct.pack(">BB", data.oath_type | data.hash_algorithm, data.digits) + secret)
            if touch:
                body += Tlv(yoath.TAG_PROPERTY, bytes([yoath.PROP_REQUIRE_TOUCH]))
            if data.counter > 0:
                body += Tlv(yoath.TAG_IMF, struct.pack(">I", data.counter))
            s.protocol.send_apdu(0, yoath.INS_PUT, 0, 0, body)
            return Credential(s.device_id, data.get_id(), data.issuer, data.name, data.oath_type, data.period, touch)

    def oath_delete(self, cred_id, password=None):
        with self._oath(password) as s:
            s.delete_credential(cred_id)

    def oath_rename(self, cred_id, name, issuer, password=None):
        with self._oath(password) as s:
            s.rename_credential(cred_id, name, issuer)

    def oath_set_password(self, new, password=None):
        with self._oath(password) as s:
            if new:
                s.set_key(s.derive_key(new))
            else:
                s.unset_key()

    # -- OTP slots -------------------------------------------------------------

    def otp_state(self):
        with self._yk() as yc:
            st = YubiOtpSession(yc).get_config_state()
            return {slot: (st.is_configured(slot), st.is_touch_triggered(slot) if st.is_configured(slot) else None)
                    for slot in (1, 2)}

    def otp_put(self, slot, config):
        with self._yk() as yc:
            YubiOtpSession(yc).put_configuration(SLOT(slot), config)

    def otp_delete(self, slot):
        with self._yk() as yc:
            YubiOtpSession(yc).delete_slot(SLOT(slot))

    def otp_swap(self):
        with self._yk() as yc:
            YubiOtpSession(yc).swap_slots()

    def otp_challenge(self, slot, challenge):
        with self._yk() as yc:
            return YubiOtpSession(yc).calculate_hmac_sha1(SLOT(slot), challenge)


def totp_left(code):
    return max(0, code.valid_to - int(time.time())) if code is not None else None


__all__ = ["Key", "KeyFailure", "list_keys", "stage", "totp_left", "LED_ORDERS", "OATH_TYPE"]
