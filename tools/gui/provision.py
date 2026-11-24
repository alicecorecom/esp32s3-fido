# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""Writing the published firmware to a SuperMini in download mode (no Qt).

The same path as the README's quick start: a new board gets the signed devsb
build (stage B+), and after the user has checked it, the signed release build
(stage C). Every write is preceded by reading the board's security state, and
anything that does not look exactly like the expected stage stops here, as
idf.ps1 does:

    new board -> B+ : SPI_BOOT_CRYPT_CNT 0, Secure Boot off, all key purposes 0
    B         -> B+ : CRYPT_CNT 1, Secure Boot off (flash encryption, dev mode)
    B+        -> C  : CRYPT_CNT 1, Secure Boot on, and every published key's
                      digest is in a non-revoked SECURE_BOOT_DIGESTn block

Only the four images of the verified zip are written, at fixed addresses: the
zip's own flash_args files are not covered by verify_release and are ignored.
"""
import contextlib
import glob
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from types import SimpleNamespace

import serial.tools.list_ports

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import espsecure  # noqa: E402
import verify_release  # noqa: E402
from esptool import cmds as ecmds  # noqa: E402
from esptool.logger import TemplateLogger, log  # noqa: E402

REPO = verify_release.REPO
ESP_VID, USB_JTAG_PID = 0x303A, 0x1001
LAYOUT = [(0x0, "bootloader/bootloader.bin"), (0x10000, "partition_table/partition-table.bin"),
          (0x18000, "ota_data_initial.bin"), (0x20000, "pico_fido.bin")]
REVOKE_FLAGS = ["SECURE_BOOT_KEY_REVOKE0", "SECURE_BOOT_KEY_REVOKE1", "SECURE_BOOT_KEY_REVOKE2"]
SB_DIGEST_PURPOSES = {9: 0, 10: 1, 11: 2}          # SECURE_BOOT_DIGEST0..2


class Stop(Exception):
    """Do not write: the message says why."""


def keys_dir():
    """keys/ of the repository, or the copy bundled into the exe."""
    base = getattr(sys, "_MEIPASS", None)
    return os.path.join(base, "keys") if base else os.path.join(os.path.dirname(TOOLS), "keys")


def public_keys():
    keys = sorted(glob.glob(os.path.join(keys_dir(), "*.pub.pem")))
    if len(keys) != 2:
        raise Stop(f"公開鍵が見つかりません（{keys_dir()}）")
    return keys


def key_digest(pem_path):
    fd, out = tempfile.mkstemp()
    os.close(fd)
    try:
        with open(pem_path, "rb") as f, contextlib.redirect_stdout(io.StringIO()):
            try:
                espsecure.digest_sbv2_public_key(f, out)                                # esptool v5
            except TypeError:
                espsecure.digest_sbv2_public_key(SimpleNamespace(keyfile=f, output=out))  # v4
        return open(out, "rb").read()
    finally:
        os.remove(out)


def find_gh():
    """GitHub CLI, also at its default install place when it is not on PATH (verify_release runs "gh")."""
    gh = shutil.which("gh")
    if gh:
        return gh
    for d in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "GitHub CLI"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GitHub CLI")):
        if os.path.exists(os.path.join(d, "gh.exe")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            return os.path.join(d, "gh.exe")
    return None


def download_ports():
    """COM ports of ESP32-S3 boards in download mode (USB-Serial/JTAG). Listing only, no I/O."""
    return [p.device for p in serial.tools.list_ports.comports() if p.vid == ESP_VID and p.pid == USB_JTAG_PID]


# ------------------------------------------------------------ the firmware

def _get(url, accept="application/octet-stream"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "esp32s3-fido-manager"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_latest(dest, say):
    """Download the latest release's devsb / release zips (signed and unsigned) into dest."""
    rel = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/latest", "application/vnd.github+json"))
    tag = rel["tag_name"]
    want = [f"esp32s3-fido-{tag}-{p}{s}.zip" for p in ("devsb", "release") for s in ("", "-unsigned")]
    assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
    missing = [w for w in want if w not in assets]
    if missing:
        raise Stop(f"{tag} に必要なファイルがありません：{', '.join(missing)}")
    for name in want:
        say(f"ダウンロード：{name}")
        with open(os.path.join(dest, name), "wb") as f:
            f.write(_get(assets[name]))
    return tag


class Firmware:
    """A verified pair of devsb / release zips."""

    def __init__(self, folder, say):
        self.folder = folder
        self.zips = {}
        for profile in ("devsb", "release"):
            signed = [p for p in glob.glob(os.path.join(folder, f"esp32s3-fido-*-{profile}.zip"))]
            if len(signed) != 1:
                raise Stop(f"{profile} の zip がちょうど1つ必要です（{folder}）")
            unsigned = signed[0][:-4] + "-unsigned.zip"
            if not os.path.exists(unsigned):
                raise Stop(f"{os.path.basename(unsigned)} がありません（本物か確かめるのに使います）")
            self.zips[profile] = (signed[0], unsigned)
        self.version = os.path.basename(self.zips["devsb"][0])[len("esp32s3-fido-"):-len("-devsb.zip")]
        self.verify(say)

    def verify(self, say):
        gh = find_gh()
        self.attested = bool(gh)
        keys = public_keys()
        for profile, (signed, unsigned) in self.zips.items():
            say(f"確認：{os.path.basename(signed)}")
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    verify_release.verify(signed, unsigned, keys, check_attestation=bool(gh))
            except (verify_release.Fail, SystemExit, subprocess.CalledProcessError) as e:
                raise Stop(f"{os.path.basename(signed)} は本物と確かめられませんでした：{e}\n{out.getvalue()}")
            for line in out.getvalue().splitlines():
                say("  " + line.strip())
        if not gh:
            say("GitHub CLI（gh）が無いので、attestation の確認は省きました（署名の確認はしました）")

    def images(self, profile):
        files = verify_release.zip_files(self.zips[profile][0])
        return [(addr, files[name]) for addr, name in LAYOUT]


# ------------------------------------------------------------ the board

class GuiLogger(TemplateLogger):
    def __init__(self, say, progress):
        self.say, self.prog = say, progress

    def print(self, message="", *args, **kwargs):
        if str(message).strip():
            self.say(str(message).rstrip())

    def note(self, message):
        self.say(f"Note: {message}")

    def warning(self, message):
        self.say(f"Warning: {message}")

    def error(self, message):
        self.say(f"Error: {message}")

    def stage(self, finish=False):
        pass

    def progress_bar(self, cur_iter, total_iters, prefix="", suffix="", bar_length=30):
        self.prog(cur_iter, total_iters)

    def set_verbosity(self, verbosity):
        pass


@contextlib.contextmanager
def connect(port, say, progress=lambda a, b: None):
    """An esptool connection to a board already in download mode (no stub, no reset)."""
    log.set_logger(GuiLogger(say, progress))
    esp = ecmds.detect_chip(port, connect_mode="no-reset", connect_attempts=3)
    try:
        if esp.CHIP_NAME != "ESP32-S3":
            raise Stop(f"ESP32-S3 ではありません（{esp.CHIP_NAME}）")
        yield esp
    finally:
        try:
            esp._port.close()
        except Exception:
            pass


def read_state(port, say):
    """What the board is, and what may be written to it."""
    with connect(port, say) as esp:
        si = esp.get_security_info()
        st = {
            "mac": ":".join(f"{b:02x}" for b in esp.read_mac()) if not esp.secure_download_mode else "（読めません）",
            "secure_download": bool(esp.secure_download_mode),
            "crypt_cnt": si["flash_crypt_cnt"],
            "sb": bool(si["parsed_flags"]["SECURE_BOOT_EN"]),
            "purposes": list(si["key_purposes"])[:6],
            "revoked": [i for i, k in enumerate(REVOKE_FLAGS) if si["parsed_flags"][k]],
            "digests": {},
        }
        if st["sb"] and not st["secure_download"]:
            from espefuse import init_commands
            with contextlib.redirect_stdout(io.StringIO()):
                efuses = init_commands(esp=esp).efuses
            for blk, purpose in enumerate(st["purposes"]):
                if purpose in SB_DIGEST_PURPOSES:
                    raw = efuses[f"BLOCK_KEY{blk}"].get_raw(from_read=True)
                    st["digests"][SB_DIGEST_PURPOSES[purpose]] = bytes(raw)
    st["stage"], st["next"], st["why"] = classify(st)
    return st


def classify(st):
    """(stage, next write or None, explanation)."""
    if st["secure_download"]:
        return "C", None, "本番の段階（C）です。ファームの更新は「ファーム」タブから USB で行います"
    fe_on = bin(st["crypt_cnt"]).count("1") % 2 == 1
    if st["crypt_cnt"] == 0 and not st["sb"]:
        if all(p == 0 for p in st["purposes"]):
            return "新品", "devsb-new", "新品です。1回目の書き込み（B+）ができます"
        return "A", None, "段階 A（暗号化なし）の基板です。この画面では扱いません（docs/releases.md の「ほかの書き込み方」）"
    if st["crypt_cnt"] == 1 and fe_on and not st["sb"]:
        return "B", "devsb-b", "段階 B（開発モードの暗号化）です。B+ に進められます"
    if st["crypt_cnt"] == 1 and fe_on and st["sb"]:
        want = {key_digest(k) for k in public_keys()}
        # espefuse's get_raw() gives the block reversed (checked on a B+ board: 0a 56 45 e7 ... = de 92 d4 cf ... reversed)
        live = {d[::-1] for slot, d in st["digests"].items() if slot not in st["revoked"]}
        if want <= live:
            return "B+", "release", "段階 B+ で、作者の鍵が焼かれています。2回目の書き込み（C）ができます"
        return "B+（別の鍵）", None, ("セキュアブートの鍵が配布版の鍵と違います（自分の鍵で作った基板？）。"
                                      "配布版は起動しないので書きません")
    return "不明", None, f"想定していない状態です（SPI_BOOT_CRYPT_CNT {st['crypt_cnt']:#x}、セキュアブート {'有効' if st['sb'] else '無効'}）。書きません"


def write(port, fw, step, say, progress):
    """step: 'devsb-new' (plaintext), 'devsb-b' (encrypted), 'release' (encrypted, --force)."""
    st = read_state(port, say)                         # check again right before writing
    if st["next"] != step:
        raise Stop(f"基板の状態が変わりました：{st['why']}")
    profile = "release" if step == "release" else "devsb"
    images = fw.images(profile)
    encrypt = step != "devsb-new"
    with connect(port, say, progress) as esp:
        ecmds.attach_flash(esp)
        ecmds.write_flash(esp, [(a, d) for a, d in images], flash_freq="80m", flash_mode="dio", flash_size="keep",
                          encrypt=encrypt, force=(step == "release"), compress=None, no_compress=False)
    say("書き込みが終わりました。基板の RST を押してください（BOOT は押さない）")
    return hashlib.sha256(images[3][1]).hexdigest()
