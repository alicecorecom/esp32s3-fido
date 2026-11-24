# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""esp32s3-fido Manager: a PyQt6 window over keydev.Key."""
import os
import secrets
import string
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keydev  # noqa: E402
from keydev import Key, KeyFailure  # noqa: E402

TOUCH = "LED が青く点滅したら、BOOT を押すかタッチパッドに触れてください（15秒）"


# ---------------------------------------------------------------- errors

def explain(e):
    """A Japanese message for the errors users actually hit."""
    from fido2.ctap import CtapError
    from yubikit.core.smartcard import ApduError
    if isinstance(e, KeyFailure):
        return str(e)
    if isinstance(e, CtapError):
        c = CtapError.ERR
        return {
            c.PIN_INVALID: "PIN が違います",
            c.PIN_BLOCKED: "PIN の失敗が多すぎてロックされました。リセットするしかありません",
            c.PIN_AUTH_BLOCKED: "PIN を3回続けて間違えました。キーを挿し直してから、もう一度試してください",
            c.PIN_POLICY_VIOLATION: "PIN が短すぎるか、条件を満たしていません（8文字以上）",
            c.PIN_NOT_SET: "PIN が設定されていません",
            c.NOT_ALLOWED: "許可されていない操作です（リセットは、挿してから10秒以内に始める必要があります）",
            c.USER_ACTION_TIMEOUT: "時間切れです（BOOT かタッチが押されませんでした）",
            c.OPERATION_DENIED: "キャンセルされました",
            c.UNSUPPORTED_OPTION: "このキーでは使えない設定です",
        }.get(e.code, f"FIDO のエラー：{e.code.name}")
    if isinstance(e, ApduError):
        return {
            0x6982: "本人確認がされませんでした（時間切れかキャンセル）、またはパスワードが必要です",
            0x6984: "キーがイメージを受け付けませんでした（署名・巻き戻し防止の版番号・形式）",
            0x6A80: "データが正しくありません",
            0x6985: "条件を満たしていません",
        }.get(e.sw, f"キーのエラー：SW {e.sw:04X}")
    if isinstance(e, keydev.fwupdate.KeyError_):
        return str(e)
    return f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- worker

class Worker(QObject):
    """One background thread for every key call (they block on BOOT / touch)."""
    finished = pyqtSignal(object, object)          # callback, result
    busy_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = 0
        self.finished.connect(lambda cb, r: cb(r))

    def run(self, fn, ok=None, err=None, busy=""):
        self.pending += 1
        if busy:
            self.busy_changed.emit(busy)

        def job():
            try:
                r = fn()
                self.finished.emit(self._done(ok), r)
            except Exception as e:                  # noqa: BLE001  shown to the user
                traceback.print_exc()
                self.finished.emit(self._done(err or show_error), e)
        self.pool.submit(job)

    def _done(self, cb):
        def wrapped(r):
            self.pending -= 1
            if self.pending == 0:
                self.busy_changed.emit("")
            if cb:
                cb(r)
        return wrapped

    @property
    def idle(self):
        return self.pending == 0


def relaunch_as_admin():
    """Start this program again elevated (UAC prompt) and quit this one."""
    import ctypes
    import subprocess
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, sys.argv[1:]
    else:
        exe, args = sys.executable, ["-I", os.path.abspath(sys.argv[0])] + sys.argv[1:]
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), os.getcwd(), 1)
    if r > 32:                                      # started (the user accepted the UAC prompt)
        QApplication.quit()


def show_error(e):
    QMessageBox.warning(None, "エラー", explain(e))


def ask_secret(parent, title, label):
    text, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Password)
    return text if ok else None


def confirm(parent, title, text):
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


def form_label(text=""):
    lab = QLabel(text)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lab.setWordWrap(True)
    return lab


class TouchPrompt(QDialog):
    """Shown while the key waits for BOOT / touch; closed when the call returns (or, for an
    update, when writing starts)."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.setWindowTitle("キーで確認してください")
        self.setModal(False)
        lay = QVBoxLayout(self)
        title = QLabel("キーの LED が青く点滅しています")
        f = title.font()
        f.setPointSize(f.pointSize() + 5)
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        body = QLabel("<b>BOOT ボタンを押す</b> か、<b>タッチパッドに触れて</b> ください。<br>15秒で時間切れになります。")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        lay.addWidget(body)
        self.setMinimumWidth(420)

    def show_centered(self, win):
        self.adjustSize()
        g = win.frameGeometry()
        self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)
        self.show()
        self.raise_()


class Page(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win

    @property
    def key(self):
        return self.win.key

    def run(self, fn, ok=None, err=None, busy=""):
        if self.key is None:
            QMessageBox.information(self, "キーがありません", "キーを挿してください")
            return
        self.win.worker.run(fn, ok, err, busy)

    def refresh(self):
        pass

    def key_changed(self):
        self.refresh()


# ---------------------------------------------------------------- overview

class OverviewPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        self.fw = QGroupBox("ファームウェア")
        self.fw_form = QFormLayout(self.fw)
        self.fido = QGroupBox("FIDO2（パスキー）")
        self.fido_form = QFormLayout(self.fido)
        self.dev = QGroupBox("キー")
        self.dev_form = QFormLayout(self.dev)
        for g in (self.fw, self.fido, self.dev):
            lay.addWidget(g)
        lay.addStretch()
        self.labels = {}
        for form, rows in ((self.fw_form, ["版", "段階", "セキュアブート", "フラッシュの暗号化", "起動している面", "巻き戻し防止の版番号", "ELF SHA-256", "LED の色順"]),
                           (self.fido_form, ["PIN", "PIN の最短の長さ", "常に本人確認（alwaysUv）", "AAGUID", "対応する版"]),
                           (self.dev_form, ["読み取り器", "シリアル番号", "有効な機能"])):
            for r in rows:
                self.labels[r] = form_label("—")
                form.addRow(r + "：", self.labels[r])

    def set(self, name, value):
        self.labels[name].setText(str(value))

    def refresh(self):
        for lab in self.labels.values():
            lab.setText("—")
        if self.key is None:
            return
        self.set("読み取り器", self.key.reader_name)
        self.run(self.key.fw_info, self.show_fw)
        self.run(self.key.fido_info, self.show_fido, self.fido_failed)
        self.run(self.key.device_info, self.show_dev)

    def show_fw(self, i):
        f = i["flags"]
        letter, text = keydev.stage(f)
        self.set("版", f"{i['version']}（{i['date']} {i['time']} ビルド、ESP-IDF {i['idf']}）")
        self.set("段階", f"{letter}：{text}")
        self.set("セキュアブート", "有効" if f & 1 else "無効")
        self.set("フラッシュの暗号化", ("release（本番）" if f & 4 else "開発モード") if f & 2 else "なし")
        state = keydev.fwupdate.STATES.get(i["state"], i["state"])
        self.set("起動している面", f"ota_{i['slot']}（{state}）")
        self.set("巻き戻し防止の版番号", f"アプリ {i['app_secure_version']}、eFuse {i['efuse_secure_version']}")
        self.set("ELF SHA-256", i["elf_sha256"])
        lo = i["led_order"]
        self.set("LED の色順", "不明（古いファーム）" if lo is None else "既定（grb）" if lo == 0xFF else keydev.LED_ORDERS[lo])

    def fido_failed(self, e):
        if isinstance(e, KeyFailure) and str(e) == keydev.ADMIN_REQUIRED:
            self.set("PIN", "管理者権限が要ります（「パスキー」タブから起動し直せます）")
        else:
            self.set("PIN", f"読めません：{explain(e)}")

    def show_fido(self, r):
        info, retries = r
        has_pin = info.options.get("clientPin")
        self.set("PIN", f"設定済み（残り {retries} 回）" if has_pin else "未設定")
        self.set("PIN の最短の長さ", f"{info.min_pin_length} 文字")
        self.set("常に本人確認（alwaysUv）", "有効" if info.options.get("alwaysUv") else "無効")
        self.set("AAGUID", str(info.aaguid))
        self.set("対応する版", ", ".join(info.versions))

    def show_dev(self, d):
        self.set("シリアル番号", d.serial)
        from yubikit.management import CAPABILITY
        enabled = next(iter(d.config.enabled_capabilities.values()), CAPABILITY(0))
        supported = next(iter(d.supported_capabilities.values()), CAPABILITY(0))
        self.set("有効な機能", ", ".join(c.name for c in CAPABILITY if c in enabled and c in supported) or "なし")


# ---------------------------------------------------------------- FIDO

class FidoPage(Page):
    def __init__(self, win):
        super().__init__(win)
        self.pin = None             # kept in memory while this key stays selected
        lay = QVBoxLayout(self)

        self.admin_box = QGroupBox("管理者権限が要ります")
        h = QHBoxLayout(self.admin_box)
        h.addWidget(form_label("Windows では、ブラウザと Windows 以外のアプリがパスキー（FIDO）を扱うには管理者権限が要ります。"
                               "ほかのタブ（ワンタイムパスワード、OTP スロット、ファーム、キーを作る）は今のままで使えます。"), 1)
        b = QPushButton("管理者として起動し直す")
        b.clicked.connect(relaunch_as_admin)
        h.addWidget(b)
        self.admin_box.setVisible(keydev.is_windows_non_admin())
        lay.addWidget(self.admin_box)

        g = QGroupBox("PIN")
        h = QHBoxLayout(g)
        self.pin_label = form_label("—")
        self.pin_btn = QPushButton("PIN を設定")
        self.pin_btn.clicked.connect(self.set_pin)
        h.addWidget(self.pin_label, 1)
        h.addWidget(self.pin_btn)
        lay.addWidget(g)

        g = QGroupBox("パスキー（このキーに保存されているもの）")
        v = QVBoxLayout(g)
        self.cred_label = form_label("一覧を見るには PIN が要ります。")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["サイト / ユーザー名", "表示名", "保護"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h = QHBoxLayout()
        b = QPushButton("一覧を読み込む")
        b.clicked.connect(self.load_creds)
        self.del_btn = QPushButton("選んだパスキーを削除")
        self.del_btn.clicked.connect(self.delete_cred)
        h.addWidget(b)
        h.addWidget(self.del_btn)
        h.addStretch()
        v.addWidget(self.cred_label)
        v.addWidget(self.tree)
        v.addLayout(h)
        lay.addWidget(g, 1)

        g = QGroupBox("設定（PIN が要ります）")
        f = QFormLayout(g)
        self.uv_label = form_label("—")
        b = QPushButton("切り替える")
        b.clicked.connect(self.toggle_uv)
        row = QHBoxLayout()
        row.addWidget(self.uv_label, 1)
        row.addWidget(b)
        f.addRow("常に本人確認（alwaysUv）：", row)
        self.min_label = form_label("—")
        b = QPushButton("上げる")
        b.clicked.connect(self.raise_min)
        row = QHBoxLayout()
        row.addWidget(self.min_label, 1)
        row.addWidget(b)
        f.addRow("PIN の最短の長さ：", row)
        b = QPushButton("次に使うとき PIN の変更を求める")
        b.clicked.connect(self.force_change)
        f.addRow("", b)
        lay.addWidget(g)

        g = QGroupBox("リセット")
        h = QHBoxLayout(g)
        h.addWidget(form_label("パスキーと PIN を全部消します。ワンタイムパスワードと OTP スロットは消えません。"), 1)
        b = QPushButton("リセット...")
        b.clicked.connect(self.reset)
        h.addWidget(b)
        lay.addWidget(g)

    def key_changed(self):
        self.pin = None
        self.tree.clear()
        self.cred_label.setText("一覧を見るには PIN が要ります。")
        self.refresh()

    def refresh(self):
        if self.key is None:
            return
        self.run(self.key.fido_info, self.show_info, self.info_failed)

    def info_failed(self, e):
        if isinstance(e, KeyFailure) and str(e) == keydev.ADMIN_REQUIRED:
            self.admin_box.setVisible(True)
            self.pin_label.setText("管理者権限が要ります（上のボタンから起動し直してください）")
        else:
            self.pin_label.setText(f"読めません：{explain(e)}")

    def show_info(self, r):
        info, retries = r
        self.has_pin = bool(info.options.get("clientPin"))
        self.pin_label.setText(f"設定済み（間違えられる残りの回数：{retries}）" if self.has_pin else "未設定")
        self.pin_btn.setText("PIN を変更" if self.has_pin else "PIN を設定")
        self.uv_label.setText("有効（ログインのたびに PIN を求める）" if info.options.get("alwaysUv") else "無効")
        self.min_label.setText(f"{info.min_pin_length} 文字（下げるにはリセットが要ります）")
        self.min_pin = info.min_pin_length

    def get_pin(self):
        if self.pin is None:
            self.pin = ask_secret(self, "PIN", "キーの PIN：")
        return self.pin

    def pin_failed(self, e):
        self.pin = None
        show_error(e)
        self.refresh()

    def set_pin(self):
        old = None
        if getattr(self, "has_pin", False):
            old = ask_secret(self, "PIN の変更", "今の PIN：")
            if old is None:
                return
        new = ask_secret(self, "PIN", "新しい PIN（8文字以上。英字や記号も使えます）：")
        if new is None:
            return
        if new != ask_secret(self, "PIN", "もう一度："):
            QMessageBox.warning(self, "PIN", "2回の入力が違います")
            return
        if len(new) < getattr(self, "min_pin", 8):
            QMessageBox.warning(self, "PIN", f"{self.min_pin} 文字以上にしてください")
            return
        fn = (lambda: self.key.fido_change_pin(old, new)) if old is not None else (lambda: self.key.fido_set_pin(new))

        def ok(_):
            self.pin = None
            QMessageBox.information(self, "PIN", "PIN を設定しました")
            self.refresh()
        self.run(fn, ok, self.pin_failed)

    def load_creds(self):
        pin = self.get_pin()
        if pin is None:
            return
        self.run(lambda: self.key.fido_credentials(pin), self.show_creds, self.pin_failed, "パスキーを読み込んでいます")

    def show_creds(self, r):
        from fido2.ctap2 import CredentialManagement as CM
        rps, meta = r
        self.tree.clear()
        n = meta.get(CM.RESULT.EXISTING_CRED_COUNT, 0)
        left = meta.get(CM.RESULT.MAX_REMAINING_COUNT)
        self.cred_label.setText(f"{n} 件" + (f"（あと {left} 件保存できます）" if left is not None else ""))
        protect = {1: "", 2: "ID が要る", 3: "本人確認が要る"}
        for rp, creds in rps:
            rp_item = QTreeWidgetItem([rp[CM.RESULT.RP].get("id", "?"), "", ""])
            for c in creds:
                u = c[CM.RESULT.USER]
                it = QTreeWidgetItem([u.get("name", "") or "(名前なし)", u.get("displayName", ""),
                                      protect.get(c.get(CM.RESULT.CRED_PROTECT), "")])
                it.setData(0, Qt.ItemDataRole.UserRole, c[CM.RESULT.CREDENTIAL_ID])
                rp_item.addChild(it)
            self.tree.addTopLevelItem(rp_item)
            rp_item.setExpanded(True)
        self.refresh()

    def delete_cred(self):
        it = self.tree.currentItem()
        cid = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        if cid is None:
            QMessageBox.information(self, "削除", "消すパスキー（ユーザー名の行）を選んでください")
            return
        site = it.parent().text(0)
        if not confirm(self, "パスキーの削除", f"{site} の {it.text(0)} を削除します。元に戻せません。\n"
                       "そのサイトには、このキーでログインできなくなります。"):
            return
        pin = self.get_pin()
        if pin is None:
            return
        self.run(lambda: self.key.fido_delete_credential(pin, cid), lambda _: self.load_creds(), self.pin_failed)

    def toggle_uv(self):
        pin = self.get_pin()
        if pin is None:
            return
        self.run(lambda: self.key.fido_toggle_always_uv(pin), lambda _: self.refresh(), self.pin_failed)

    def raise_min(self):
        cur = getattr(self, "min_pin", 8)
        n, ok = QInputDialog.getInt(self, "PIN の最短の長さ", "新しい最短の長さ（今より長く。下げるにはリセットが要ります）：",
                                    cur + 1, cur + 1, 63)
        if not ok:
            return
        if not confirm(self, "PIN の最短の長さ", f"最短を {n} 文字にします。今の PIN がそれより短ければ、次に使うとき変更を求められます。"):
            return
        pin = self.get_pin()
        if pin is None:
            return
        self.run(lambda: self.key.fido_set_min_pin(pin, length=n), lambda _: self.refresh(), self.pin_failed)

    def force_change(self):
        if not confirm(self, "PIN の変更", "次にこのキーを使うとき、PIN の変更を求めるようにします。"):
            return
        pin = self.get_pin()
        if pin is None:
            return
        self.run(lambda: self.key.fido_set_min_pin(pin, force_change=True), lambda _: self.refresh(), self.pin_failed)

    def reset(self):
        if not confirm(self, "FIDO のリセット",
                       "このキーのパスキーと PIN を全部消します。元に戻せません。\n"
                       "このキーで登録したサイトには、ログインできなくなります。\n\n続けますか？"):
            return
        QMessageBox.information(self, "FIDO のリセット",
                                "キーを抜いて挿し直してください。\n挿し直したら10秒以内に OK を押し、"
                                "LED が青く点滅したら BOOT を押すかタッチしてください。")

        def ok(_):
            self.pin = None
            self.tree.clear()
            QMessageBox.information(self, "FIDO のリセット", "リセットしました。PIN を設定し直してください。")
            self.refresh()
        # the key re-enumerates after the replug; give list_keys a moment
        self.win.rescan_now()
        QTimer.singleShot(300, lambda: self.run(self.key.fido_reset, ok, None, TOUCH))


# ---------------------------------------------------------------- OATH

class OathAddDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("ワンタイムパスワードの追加")
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        self.tabs = tabs
        w = QWidget()
        f = QFormLayout(w)
        self.uri = QLineEdit()
        self.uri.setEchoMode(QLineEdit.EchoMode.Password)
        self.uri.setPlaceholderText("otpauth://totp/...")
        f.addRow("URL：", self.uri)
        f.addRow("", form_label("サイトの QR コードを読み取ったときの otpauth:// で始まる文字列を貼ります。"))
        tabs.addTab(w, "URL から")
        w = QWidget()
        f = QFormLayout(w)
        self.issuer = QLineEdit()
        self.name = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.kind = QComboBox()
        self.kind.addItems(["TOTP（時間ごと）", "HOTP（押すたび）"])
        self.digits = QComboBox()
        self.digits.addItems(["6", "7", "8"])
        self.period = QSpinBox()
        self.period.setRange(15, 300)
        self.period.setValue(30)
        self.algo = QComboBox()
        self.algo.addItems(["SHA1", "SHA256", "SHA512"])
        f.addRow("サービス名：", self.issuer)
        f.addRow("アカウント名：", self.name)
        f.addRow("秘密鍵（Base32）：", self.secret)
        f.addRow("種類：", self.kind)
        f.addRow("桁数：", self.digits)
        f.addRow("間隔（秒）：", self.period)
        f.addRow("アルゴリズム：", self.algo)
        tabs.addTab(w, "秘密鍵から")
        lay.addWidget(tabs)
        self.touch = QCheckBox("コードを出すたびに BOOT / タッチを求める")
        lay.addWidget(self.touch)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def data(self):
        from yubikit.oath import HASH_ALGORITHM, OATH_TYPE, CredentialData, parse_b32_key
        if self.tabs.currentIndex() == 0:
            return CredentialData.parse_uri(self.uri.text().strip())
        if not self.name.text().strip():
            raise ValueError("アカウント名を入れてください")
        return CredentialData(name=self.name.text().strip(), issuer=self.issuer.text().strip() or None,
                              oath_type=OATH_TYPE.HOTP if self.kind.currentIndex() else OATH_TYPE.TOTP,
                              hash_algorithm=HASH_ALGORITHM[self.algo.currentText()],
                              secret=parse_b32_key(self.secret.text().strip()),
                              digits=int(self.digits.currentText()), period=self.period.value())


def oath_label(c):
    return f"{c.issuer}:{c.name}" if c.issuer else c.name


class OathPage(Page):
    def __init__(self, win):
        super().__init__(win)
        self.password = None
        self.rows = []              # [(cred, code, touch)]
        lay = QVBoxLayout(self)
        lay.addWidget(form_label("ダブルクリックでコードをコピーします。タッチが必要なものや HOTP は、ダブルクリックしたときに計算します。"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["アカウント", "コード", "残り"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.copy_row)
        lay.addWidget(self.table, 1)
        h = QHBoxLayout()
        for text, fn in (("更新", self.refresh), ("追加...", self.add), ("名前の変更...", self.rename),
                         ("削除", self.delete), ("パスワード...", self.set_password)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        lay.addLayout(h)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def key_changed(self):
        self.password = None
        self.rows = []
        self.table.setRowCount(0)
        self.refresh()

    def oath_call(self, fn, ok, busy=""):
        """Run fn(password); ask for the OATH password once if the key is locked."""
        def err(e):
            if isinstance(e, KeyFailure) and str(e) == "OATH_LOCKED" or \
                    getattr(e, "sw", None) == 0x6982 and self.password is not None:
                self.password = ask_secret(self, "OATH のパスワード", "ワンタイムパスワードのパスワード：")
                if self.password is not None:
                    self.run(lambda: fn(self.password), ok, err, busy)
                return
            show_error(e)
        self.run(lambda: fn(self.password), ok, err, busy)

    def refresh(self):
        if self.key is None or not self.isVisible():
            return
        self.oath_call(lambda pw: self.key.oath_codes(pw), self.show)

    def show(self, rows):
        self.rows = sorted(rows, key=lambda r: oath_label(r[0]).lower())
        self.table.setRowCount(len(self.rows))
        mono = QFont("Consolas")
        mono.setPointSize(13)
        for i, (c, code, touch) in enumerate(self.rows):
            self.table.setItem(i, 0, QTableWidgetItem(oath_label(c) + ("（タッチ）" if touch else "")))
            if code is not None:
                text = code.value
            elif c.oath_type == keydev.OATH_TYPE.HOTP:
                text = "ダブルクリックで計算"
            else:
                text = "ダブルクリックでタッチ"
            it = QTableWidgetItem(text)
            if code is not None:
                it.setFont(mono)
            self.table.setItem(i, 1, it)
            self.table.setItem(i, 2, QTableWidgetItem(""))
        self.tick()

    def tick(self):
        expired = False
        for i, (c, code, _) in enumerate(self.rows):
            left = keydev.totp_left(code) if c.oath_type == keydev.OATH_TYPE.TOTP else None
            item = self.table.item(i, 2)
            if item is not None:
                item.setText(f"{left} 秒" if left is not None else "")
            if left == 0:
                expired = True
        # only while the window is in front: a card call during a browser's FIDO request can disturb it
        if expired and self.win.worker.idle and self.isVisible() and self.win.isActiveWindow():
            self.refresh()

    def copy_row(self, row, _col):
        c, code, touch = self.rows[row]
        if code is not None and (c.oath_type != keydev.OATH_TYPE.TOTP or keydev.totp_left(code) > 0):
            self.copy(code.value)
            return

        def ok(code):
            self.rows[row] = (c, code, touch)
            self.table.item(row, 1).setText(code.value)
            self.copy(code.value)
            self.tick()
        self.oath_call(lambda pw: self.key.oath_calculate(c, pw), ok, TOUCH if touch else "")

    def copy(self, text):
        QGuiApplication.clipboard().setText(text)
        self.win.statusBar().showMessage(f"コピーしました：{text}", 4000)

    def selected(self):
        r = self.table.currentRow()
        return self.rows[r][0] if 0 <= r < len(self.rows) else None

    def add(self):
        d = OathAddDialog(self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            data = d.data()
        except Exception as e:                      # noqa: BLE001
            QMessageBox.warning(self, "追加", f"内容が正しくありません：{e}")
            return
        lab = f"{data.issuer}:{data.name}" if data.issuer else data.name
        if any(oath_label(c) == lab for c, _, _ in self.rows) and \
                not confirm(self, "追加", f"{lab} はもうあります。上書きしますか？"):
            return
        touch = d.touch.isChecked()
        self.oath_call(lambda pw: self.key.oath_put(data, touch, pw), lambda _: self.refresh())

    def rename(self):
        c = self.selected()
        if c is None:
            return
        issuer, ok = QInputDialog.getText(self, "名前の変更", "サービス名：", text=c.issuer or "")
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "名前の変更", "アカウント名：", text=c.name)
        if not ok or not name.strip():
            return
        self.oath_call(lambda pw: self.key.oath_rename(c.id, name.strip(), issuer.strip() or None, pw),
                       lambda _: self.refresh())

    def delete(self):
        c = self.selected()
        if c is None:
            return
        if not confirm(self, "削除", f"{oath_label(c)} を削除します。元に戻せません。\n"
                       "そのサービスの2段階認証を、ほかの方法で通れることを確かめてから消してください。"):
            return
        self.oath_call(lambda pw: self.key.oath_delete(c.id, pw), lambda _: self.refresh())

    def set_password(self):
        new = ask_secret(self, "OATH のパスワード", "新しいパスワード（空にすると外します）：")
        if new is None:
            return
        if new and new != ask_secret(self, "OATH のパスワード", "もう一度："):
            QMessageBox.warning(self, "パスワード", "2回の入力が違います")
            return

        def ok(_):
            self.password = new or None
            QMessageBox.information(self, "パスワード", "設定しました" if new else "外しました")
            self.refresh()
        self.oath_call(lambda pw: self.key.oath_set_password(new, pw), ok)


# ---------------------------------------------------------------- OTP slots

class OtpDialog(QDialog):
    KINDS = ["チャレンジレスポンス（HMAC-SHA1）", "HOTP（押すと6桁を打つ）", "静的パスワード（押すと決まった文字列を打つ）"]

    def __init__(self, parent, slot):
        super().__init__(parent)
        self.setWindowTitle(f"スロット {slot} の設定")
        f = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(self.KINDS)
        f.addRow("種類：", self.kind)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        gen = QPushButton("ランダムに作る")
        gen.clicked.connect(self.generate)
        self.show_secret = QCheckBox("表示する")
        self.show_secret.toggled.connect(lambda on: self.secret.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        row = QHBoxLayout()
        row.addWidget(self.secret, 1)
        row.addWidget(gen)
        row.addWidget(self.show_secret)
        f.addRow("秘密：", row)
        self.hint = form_label()
        f.addRow("", self.hint)
        self.touch = QCheckBox("計算のたびに BOOT / タッチを求める")
        self.touch.setChecked(True)
        f.addRow("", self.touch)
        self.digits8 = QCheckBox("8桁にする")
        f.addRow("", self.digits8)
        self.enter = QCheckBox("最後に Enter を押す")
        self.enter.setChecked(True)
        f.addRow("", self.enter)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.kind.currentIndexChanged.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        k = self.kind.currentIndex()
        self.touch.setVisible(k == 0)
        self.digits8.setVisible(k == 1)
        self.enter.setVisible(k in (1, 2))
        self.hint.setText([
            "16進数で最大20バイト（40文字）。KeePassXC などのチャレンジレスポンスに使います。控えを取っておくこと",
            "Base32 の秘密鍵（サイトが表示するもの）",
            "英字と数字だけ、38文字まで。日本語キーボードでは記号の位置がずれるため、記号は使えません",
        ][k])

    def generate(self):
        k = self.kind.currentIndex()
        if k == 0:
            self.secret.setText(secrets.token_hex(20))
        elif k == 1:
            import base64
            self.secret.setText(base64.b32encode(secrets.token_bytes(20)).decode())
        else:
            alphabet = string.ascii_letters + string.digits
            self.secret.setText("".join(secrets.choice(alphabet) for _ in range(32)))
        self.show_secret.setChecked(True)

    def config(self):
        from ykman.scancodes import KEYBOARD_LAYOUT, encode
        from yubikit.oath import parse_b32_key
        from yubikit.yubiotp import HmacSha1SlotConfiguration, HotpSlotConfiguration, StaticPasswordSlotConfiguration
        k, s = self.kind.currentIndex(), self.secret.text().strip()
        if k == 0:
            key = bytes.fromhex(s)
            if not 1 <= len(key) <= 20:
                raise ValueError("1〜20バイトの16進数にしてください")
            return HmacSha1SlotConfiguration(key).require_touch(self.touch.isChecked())
        if k == 1:
            return HotpSlotConfiguration(parse_b32_key(s)).digits8(self.digits8.isChecked()).append_cr(self.enter.isChecked())
        if not s or len(s) > 38 or any(ch not in string.ascii_letters + string.digits for ch in s):
            raise ValueError("英字と数字だけ、1〜38文字にしてください")
        return StaticPasswordSlotConfiguration(encode(s, KEYBOARD_LAYOUT.US)).append_cr(self.enter.isChecked())


class OtpPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        lay.addWidget(form_label("BOOT を1回押すとスロット1、すばやく2回押すとスロット2 の内容をキーボードとして打ちます"
                                 "（チャレンジレスポンスは、対応するアプリから使います）。"))
        self.labels = {}
        for slot in (1, 2):
            g = QGroupBox(f"スロット {slot}（BOOT を{'1' if slot == 1 else '2'}回）")
            h = QHBoxLayout(g)
            self.labels[slot] = form_label("—")
            h.addWidget(self.labels[slot], 1)
            b = QPushButton("設定...")
            b.clicked.connect(lambda _=False, s=slot: self.configure(s))
            h.addWidget(b)
            b = QPushButton("消す")
            b.clicked.connect(lambda _=False, s=slot: self.delete(s))
            h.addWidget(b)
            lay.addWidget(g)
        b = QPushButton("スロット1と2を入れ替える")
        b.clicked.connect(self.swap)
        lay.addWidget(b)
        lay.addStretch()

    def refresh(self):
        if self.key is None:
            return
        self.run(self.key.otp_state, self.show)

    def show(self, st):
        for slot, (configured, touch) in st.items():
            self.labels[slot].setText("設定済み" + ("（BOOT で打つ）" if touch else "（チャレンジレスポンスなど）")
                                      if configured else "空き")
        self.state = st

    def configure(self, slot):
        if getattr(self, "state", {}).get(slot, (False,))[0] and \
                not confirm(self, "スロット", f"スロット {slot} は設定済みです。上書きしますか？元の内容は戻せません。"):
            return
        d = OtpDialog(self, slot)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            cfg = d.config()
        except Exception as e:                      # noqa: BLE001
            QMessageBox.warning(self, "スロット", f"内容が正しくありません：{e}")
            return
        self.run(lambda: self.key.otp_put(slot, cfg), lambda _: self.refresh())

    def delete(self, slot):
        if not confirm(self, "スロット", f"スロット {slot} の内容を消します。元に戻せません。"):
            return
        self.run(lambda: self.key.otp_delete(slot), lambda _: self.refresh())

    def swap(self):
        self.run(self.key.otp_swap, lambda _: self.refresh())


# ---------------------------------------------------------------- firmware

class LedCheckDialog(QDialog):
    """Blink red, then green; ask what the user saw; compute the order (fwupdate.led_check)."""

    def __init__(self, page, info):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("LED の色合わせ")
        cur = info["led_order"]
        self.order = keydev.DEFAULT_LED_ORDER if cur == 0xFF else cur
        self.sel = ["rgb".index(ch) for ch in keydev.LED_ORDERS[self.order]]
        self.answers = []
        self.step = 0                                # 0 red, 1 green, 2 check red
        lay = QVBoxLayout(self)
        self.text = form_label()
        lay.addWidget(self.text)
        h = QHBoxLayout()
        for name, idx in (("赤", 0), ("緑", 1), ("青", 2)):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, i=idx: self.answer(i))
            h.addWidget(b)
        again = QPushButton("もう一度光らせる")
        again.clicked.connect(self.blink)
        h.addWidget(again)
        lay.addLayout(h)
        self.blink()

    def blink(self):
        colour = [0, 1, 0][self.step]
        self.text.setText(["1/2：LED が3回光ります。何色に見えましたか？",
                           "2/2：もう一度光ります。何色に見えましたか？",
                           "確認：今度は何色に見えましたか？"][self.step])
        self.page.run(lambda: self.page.key.led_blink(colour))

    def answer(self, seen):
        if self.step == 2:
            if seen == 0:
                QMessageBox.information(self, "LED", f"合いました（{self.new}）")
                self.accept()
            else:
                QMessageBox.warning(self, "LED", "まだ合っていません。もう一度やり直してください")
                self.reject()
            return
        self.answers.append(seen)
        if self.step == 0:
            self.step = 1
            self.blink()
            return
        seen_r, seen_g = self.answers
        if seen_r == seen_g:
            QMessageBox.warning(self, "LED", "赤と緑が同じ色に見えることはありません。やり直してください")
            self.reject()
            return
        seen_map = {0: seen_r, 1: seen_g, 2: 3 - seen_r - seen_g}
        self.new = "".join("rgb"[seen_map[self.sel[j]]] for j in range(3))
        if self.new == keydev.LED_ORDERS[self.order]:
            QMessageBox.information(self, "LED", "色は合っています。変更はありません")
            self.accept()
            return
        self.text.setText(f"色順を {self.new} にします。" + TOUCH)

        def ok(_):
            self.step = 2
            self.blink()
        self.page.run(lambda: self.page.key.led_order_set(self.new), ok, None, TOUCH)


class FirmwarePage(Page):
    def __init__(self, win):
        super().__init__(win)
        self.info = None
        self.img = None
        lay = QVBoxLayout(self)

        g = QGroupBox("ファームの更新（USB 経由）")
        v = QVBoxLayout(g)
        v.addWidget(form_label("Releases から、キーの段階に合ったファイルを選びます。本番（C）のキーは app-rel.bin、"
                               "B+ のキーは app-sb.bin。パスキーなどのデータは消えません。"))
        h = QHBoxLayout()
        self.file_label = form_label("ファイルが選ばれていません")
        b = QPushButton("ファイルを選ぶ...")
        b.clicked.connect(self.choose)
        dl = QPushButton("最新版をダウンロード")
        dl.clicked.connect(self.download)
        h.addWidget(self.file_label, 1)
        h.addWidget(dl)
        h.addWidget(b)
        v.addLayout(h)
        self.check_label = form_label("")
        v.addWidget(self.check_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.update_btn = QPushButton("更新する")
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self.do_update)
        v.addWidget(self.update_btn)
        lay.addWidget(g)

        g = QGroupBox("LED の色")
        h = QHBoxLayout(g)
        h.addWidget(form_label("成功が赤・時間切れが緑に見えるときは、色合わせをします。"), 1)
        b = QPushButton("色合わせ...")
        b.clicked.connect(self.led_check)
        h.addWidget(b)
        self.order = QComboBox()
        self.order.addItems(["default"] + keydev.LED_ORDERS)
        h.addWidget(self.order)
        b = QPushButton("この順にする")
        b.clicked.connect(self.led_set)
        h.addWidget(b)
        lay.addWidget(g)

        g = QGroupBox("その他")
        h = QHBoxLayout(g)
        b = QPushButton("キーを再起動")
        b.clicked.connect(lambda: self.run(self.key.fw_reboot, lambda _: None))
        h.addWidget(b)
        h.addStretch()
        lay.addWidget(g)
        lay.addStretch()

    def refresh(self):
        if self.key is None:
            return
        self.run(self.key.fw_info, self.got_info)

    def got_info(self, i):
        self.info = i
        lo = i["led_order"]
        if lo is not None:
            self.order.setCurrentText("default" if lo == 0xFF else keydev.LED_ORDERS[lo])
        self.check()

    def download(self):
        if self.info is None:
            QMessageBox.information(self, "ファーム", "キーの状態を読み終わってから押してください")
            return
        import tempfile
        import provision
        kind = keydev.fwupdate.key_profile(self.info)
        dest = tempfile.mkdtemp(prefix="esp32s3-fido-")
        say = lambda text: None                     # noqa: E731  (the result line says what was checked)

        def ok(r):
            path, tag, attested = r
            self.img = open(path, "rb").read()
            self.file_label.setText(f"{os.path.basename(path)}（Releases の {tag}。作者の鍵の署名"
                                    + ("と attestation" if attested else "") + " を確認済み）")
            self.check()

        def err(e):
            if isinstance(e, provision.Stop):
                QMessageBox.warning(self, "ダウンロード", str(e))
            else:
                show_error(e)
        self.win.worker.run(lambda: provision.fetch_app(kind, dest, say), ok, err, "ダウンロードして確かめています")

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "ファームを選ぶ", os.path.expanduser("~/Downloads"),
                                              "アプリのイメージ (*.bin)")
        if not path:
            return
        self.img = open(path, "rb").read()
        self.file_label.setText(path)
        self.check()

    def check(self):
        self.update_btn.setEnabled(False)
        if self.img is None or self.info is None:
            return
        fw = keydev.fwupdate
        try:
            d = fw.image_desc(self.img)
            fw.check_image(self.img, self.info, d)
        except Exception as e:                      # noqa: BLE001
            self.check_label.setText(f"このキーには使えません：{explain(e)}")
            return
        self.desc = d
        self.check_label.setText(f"{d['project']} {d['version']}（巻き戻し防止の版番号 {d['secure_version']}）\n"
                                 f"ELF SHA-256 {d['elf_sha256']}\n今のキー：{self.info['version']}")
        self.update_btn.setEnabled(True)

    def do_update(self):
        if not confirm(self, "ファームの更新", f"{self.info['version']} → {self.desc['version']} に更新します。\n"
                       "書き込みは30秒ほどかかります。終わるまでキーを抜かないでください。"):
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.update_btn.setEnabled(False)
        img = self.img
        sig = self.win.worker

        class Bridge(QObject):
            step = pyqtSignal(int, int)
        self.bridge = Bridge()
        def step(done, total):
            if self.win.touch_prompt.isVisible():   # confirmed on the key: writing has started
                self.win.touch_prompt.hide()
                self.win.busy_label.setText("書き込んでいます。終わるまでキーを抜かないでください")
            self.progress.setMaximum(total)
            self.progress.setValue(done)
        self.bridge.step.connect(step)

        def ok(_):
            self.progress.setVisible(False)
            QMessageBox.information(self, "ファームの更新",
                                    "受け付けられました。キーが再起動します。\n数秒後に「状態」で新しい版になったことを確かめてください。")
            QTimer.singleShot(5000, self.win.rescan_now)

        def err(e):
            self.progress.setVisible(False)
            show_error(e)
            self.check()
        sig.run(lambda: self.key.fw_update(img, self.bridge.step.emit), ok, err, TOUCH)

    def led_check(self):
        if self.info is None or self.info["led_order"] is None:
            QMessageBox.information(self, "LED", "このファームは色合わせに対応していません（v0.1.2 以降）")
            return
        LedCheckDialog(self, self.info).exec()
        self.refresh()

    def led_set(self):
        order = self.order.currentText()
        self.run(lambda: self.key.led_order_set(order), lambda _: self.refresh(), None, TOUCH)


# ---------------------------------------------------------------- new key

class ProvisionPage(Page):
    """README's quick start: a new board -> B+ (check) -> C, with the published firmware."""

    class Bridge(QObject):
        line = pyqtSignal(str)
        step = pyqtSignal(int, int)

    def __init__(self, win):
        super().__init__(win)
        import provision
        self.p = provision
        self.fw = None
        self.state = None
        self.bridge = self.Bridge()
        self.bridge.line.connect(self.append)
        self.bridge.step.connect(lambda a, b: (self.progress.setMaximum(max(b, 1)), self.progress.setValue(a)))
        lay = QVBoxLayout(self)
        lay.addWidget(form_label(
            "新品の SuperMini に、配布版のファームを書き込みます。1回目（B+）で動作を確かめてから、2回目で本番（C）にします。"
            "どちらも eFuse を焼くので元に戻せません。書き込んだ基板は、作者の鍵で署名したファームしか起動しなくなります。"))

        g = QGroupBox("1. ファーム")
        h = QHBoxLayout(g)
        self.fw_label = form_label("まだ選ばれていません")
        h.addWidget(self.fw_label, 1)
        b = QPushButton("最新版をダウンロード")
        b.clicked.connect(self.fetch)
        h.addWidget(b)
        b = QPushButton("フォルダを選ぶ...")
        b.clicked.connect(self.choose)
        h.addWidget(b)
        lay.addWidget(g)

        g = QGroupBox("2. 基板（BOOT を押したまま RST を押して離し、BOOT も離す）")
        f = QFormLayout(g)
        self.ports = QComboBox()
        b = QPushButton("状態を読む")
        b.clicked.connect(self.read)
        row = QHBoxLayout()
        row.addWidget(self.ports, 1)
        row.addWidget(b)
        f.addRow("COM ポート：", row)
        self.st = {k: form_label("—") for k in ("MAC", "段階", "次にできること")}
        for k, lab in self.st.items():
            f.addRow(k + "：", lab)
        lay.addWidget(g)

        g = QGroupBox("3. 書き込む")
        v = QVBoxLayout(g)
        self.write_btn = QPushButton("（状態を読むと、ここに次の書き込みが出ます）")
        self.write_btn.setEnabled(False)
        self.write_btn.clicked.connect(self.write)
        v.addWidget(self.write_btn)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.after = form_label("")
        v.addWidget(self.after)
        lay.addWidget(g)

        from PyQt6.QtWidgets import QPlainTextEdit
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        lay.addWidget(self.log, 1)

        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self.scan_ports)
        self.port_timer.start(1500)

    # -- helpers
    def append(self, text):
        self.log.appendPlainText(text)

    def say(self, text):                       # from the worker thread
        self.bridge.line.emit(text)

    def work(self, fn, ok, busy=""):
        def err(e):
            self.progress.setVisible(False)
            if isinstance(e, self.p.Stop):
                QMessageBox.warning(self, "止めました", str(e))
            else:
                show_error(e)
            self.append(f"エラー：{explain(e)}")
        self.win.worker.run(fn, ok, err, busy)

    def scan_ports(self):
        ports = self.p.download_ports()      # listing only: no I/O to the boards
        if ports != [self.ports.itemText(i) for i in range(self.ports.count())]:
            cur = self.ports.currentText()
            self.ports.clear()
            self.ports.addItems(ports)
            if cur in ports:
                self.ports.setCurrentText(cur)

    def refresh(self):
        self.scan_ports()

    def key_changed(self):
        pass

    # -- firmware
    def fetch(self):
        import tempfile
        dest = tempfile.mkdtemp(prefix="esp32s3-fido-")

        def job():
            self.p.fetch_latest(dest, self.say)
            return self.p.Firmware(dest, self.say)
        self.work(job, self.got_fw, "ダウンロードして確かめています")

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, "devsb / release の zip（署名済みと -unsigned）があるフォルダ",
                                             os.path.expanduser("~/Downloads"))
        if d:
            self.work(lambda: self.p.Firmware(d, self.say), self.got_fw, "確かめています")

    def got_fw(self, fw):
        self.fw = fw
        self.fw_label.setText(f"{fw.version}（署名を確認" + ("、attestation も確認" if fw.attested else "。attestation は gh が無いので省略") + "）")
        self.update_button()

    # -- board
    def read(self):
        port = self.ports.currentText()
        if not port:
            QMessageBox.information(self, "基板", "ダウンロードモードの基板が見つかりません。BOOT を押したまま RST を押してください")
            return
        self.work(lambda: self.p.read_state(port, self.say), self.got_state, "基板の状態を読んでいます")

    def got_state(self, st):
        self.state = st
        self.state_port = self.ports.currentText()
        self.st["MAC"].setText(st["mac"])
        self.st["段階"].setText(st["stage"])
        self.st["次にできること"].setText(st["why"])
        self.update_button()

    def update_button(self):
        nxt = self.state and self.state["next"]
        text = {"devsb-new": "1回目を書き込む（新品 → B+）", "devsb-b": "B+ にする（B → B+）",
                "release": "2回目を書き込む（B+ → 本番 C）"}.get(nxt, "書き込めるものはありません")
        if nxt and self.fw is None:
            text += "（先にファームを選んでください）"
        self.write_btn.setText(text)
        self.write_btn.setEnabled(bool(nxt) and self.fw is not None)

    def write(self):
        step = self.state["next"]
        port = self.state_port
        if step == "release":
            box = QMessageBox(QMessageBox.Icon.Warning, "本番（C）にする",
                              f"{port} の基板を本番の段階にします。元に戻せません。\n\n"
                              "・ブートローダは二度と変えられません。ファームは USB 経由の更新でしか変えられません\n"
                              "・ダウンロードモードでフラッシュを読めなくなります\n\n"
                              "B+ の段階で、LED の色合わせ・PIN の設定・登録・抜き差し後のログインを確かめましたか？",
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            cb = QCheckBox("確かめた")
            box.setCheckBox(cb)
            if box.exec() != QMessageBox.StandardButton.Yes or not cb.isChecked():
                return
        else:
            box = QMessageBox(QMessageBox.Icon.Warning, "B+ にする",
                              f"{port} の基板に {self.fw.version} の devsb を書き込みます。\n\n"
                              "最初の起動で、作者の鍵2本のダイジェストを eFuse に焼き、セキュアブートとフラッシュの暗号化を"
                              "有効にします。元に戻せません。以後は作者の鍵で署名したファームしか起動しません。\n\n続けますか？",
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.write_btn.setEnabled(False)
        fw = self.fw

        def ok(sha):
            self.progress.setVisible(False)
            self.state = None
            self.update_button()
            if step == "release":
                msg = ("書き込みました。基板の RST を押してください（BOOT は押さない）。\n\n"
                       "起動したら：抜き差ししてログインを確かめる → 「パスキー」タブでリセット → PIN を設定し直す")
            else:
                msg = ("書き込みました。基板の RST を押してください（BOOT は押さない）。最初の起動は十数秒かかり、"
                       "終わると LED が青く0.5秒光ります。\n\n"
                       "起動したら：「ファーム」タブで LED の色合わせ → 「パスキー」タブで PIN を設定 → "
                       "webauthn.io で登録し、抜き差ししてログイン → 問題なければ、もう一度ダウンロードモードにして2回目へ")
            self.after.setText(msg)
            QMessageBox.information(self, "書き込み", msg)
        self.work(lambda: self.p.write(port, fw, step, self.say, self.bridge.step.emit), ok, "書き込んでいます")


# ---------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("esp32s3-fido Manager")
        self.resize(820, 640)
        self.key = None
        self.worker = Worker()
        self.worker.busy_changed.connect(self.busy)
        self.touch_prompt = TouchPrompt(self)

        central = QWidget()
        lay = QVBoxLayout(central)
        top = QHBoxLayout()
        top.addWidget(QLabel("キー："))
        self.keys = QComboBox()
        self.keys.currentTextChanged.connect(self.select_key)
        top.addWidget(self.keys, 1)
        lay.addLayout(top)
        self.tabs = QTabWidget()
        self.pages = [OverviewPage(self), FidoPage(self), OathPage(self), OtpPage(self), FirmwarePage(self),
                      ProvisionPage(self)]
        for p, name in zip(self.pages, ["状態", "パスキー（FIDO2）", "ワンタイムパスワード", "OTP スロット", "ファーム",
                                        "キーを作る"]):
            self.tabs.addTab(p, name)
        self.tabs.currentChanged.connect(lambda i: self.pages[i].refresh())
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.busy_label = QLabel("")
        self.statusBar().addPermanentWidget(self.busy_label)

        self.scan = QTimer(self)
        self.scan.timeout.connect(self.rescan)
        self.scan.start(2000)
        self.rescan_now()

    def busy(self, text):
        self.busy_label.setText(text)
        if text == TOUCH:
            self.touch_prompt.show_centered(self)
        else:
            self.touch_prompt.hide()

    def rescan(self):
        if self.worker.idle:
            self.rescan_now()

    def rescan_now(self):
        self.worker.run(keydev.list_keys, self.got_keys, lambda e: None)

    def got_keys(self, names):
        current = self.keys.currentText()
        if names == [self.keys.itemText(i) for i in range(self.keys.count())]:
            return
        self.keys.blockSignals(True)
        self.keys.clear()
        self.keys.addItems(names)
        if current in names:
            self.keys.setCurrentText(current)
        self.keys.blockSignals(False)
        if not names:
            self.statusBar().showMessage("キーを挿してください")
        self.select_key(self.keys.currentText())

    def select_key(self, name):
        new = Key(name) if name else None
        if (new and new.reader_name) == (self.key and self.key.reader_name):
            return
        self.key = new
        for p in self.pages:
            p.key_changed()
        if new:
            self.statusBar().showMessage(f"{name} を使います", 3000)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("esp32s3-fido Manager")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
