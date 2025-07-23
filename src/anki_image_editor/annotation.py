import base64
import json
import os
import re
import sys
from pathlib import Path
from concurrent.futures import Future

import anki.find
import aqt
from anki.collection import Collection, OpChanges, OpChangesWithCount
from anki.errors import AnkiException, NotFoundError
from aqt import mw
from aqt.qt import *
from aqt.utils import askUserDialog, restoreGeom, saveGeom, showText, tooltip, showWarning
from aqt.webview import AnkiWebPage, AnkiWebView
from aqt.operations import CollectionOp, QueryOp

from .utils import checked, get_config, set_config

method_draw_path = os.path.join(
    os.path.dirname(__file__), "web", "Method-Draw", "editor", "index.html"
)

MIME_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "ico": "image/vnd.microsoft.icon",
    "svg": "image/svg+xml",
}


class myPage(AnkiWebPage):
    def acceptNavigationRequest(self, url, navType, isMainFrame):
        "Needed so the link don't get opened in external browser"
        return True


class AnnotateDialog(QDialog):
    def __init__(self, editor, name, path="", src="", create_new=False):
        QDialog.__init__(self, editor.widget, Qt.WindowType.Window)
        # Setup dialog garbage collection
        mw.setupDialogGC(self)
        self.editor_wv = editor.web
        self.editor = editor
        self.image_name = name
        self.image_path = path
        self.image_src = src
        self.create_new = create_new
        self.close_queued = False
        if not create_new:
            self.check_editor_image_selected()
        self.setupUI()

    def closeEvent(self, evt):
        if self.close_queued:
            saveGeom(self, "addon_image_editor")
            # 安全地删除属性
            if hasattr(mw, 'annodial'):
                delattr(mw, 'annodial')
            evt.accept()
        else:
            self.ask_on_close(evt)

    def setupUI(self):
        mainLayout = QVBoxLayout()
        self.setLayout(mainLayout)

        self.web = AnkiWebView(parent=self, title="Annotate Image")
        url = QUrl.fromLocalFile(method_draw_path)
        self.web._page = myPage(self.web._onBridgeCmd)
        self.web.setPage(self.web._page)
        self.web.setUrl(url)
        self.web.set_bridge_command(self.on_bridge_cmd, self)
        mainLayout.addWidget(self.web, stretch=1)

        btnLayout = QHBoxLayout()
        btnLayout.addStretch(1)

        replaceAll = QCheckBox("Replace All")
        self.replaceAll = replaceAll
        ch = get_config("replace_all", hidden=True, notexist=False)
        replaceAll.setCheckState(checked(ch))
        replaceAll.stateChanged.connect(self.check_changed)
        btnLayout.addWidget(replaceAll)

        okButton = QPushButton("Save")
        okButton.clicked.connect(self.save)
        btnLayout.addWidget(okButton)
        
        exportButton = QPushButton("Export")
        exportButton.clicked.connect(self.export_png)
        exportButton.setToolTip("Export as PNG")
        btnLayout.addWidget(exportButton)
        
        cancelButton = QPushButton("Discard")
        cancelButton.clicked.connect(self.discard)
        btnLayout.addWidget(cancelButton)
        resetButton = QPushButton("Reset")
        resetButton.clicked.connect(self.reset)
        btnLayout.addWidget(resetButton)

        okButton.setDefault(False)
        okButton.setAutoDefault(False)
        cancelButton.setDefault(False)
        cancelButton.setAutoDefault(False)
        resetButton.setDefault(False)
        resetButton.setAutoDefault(False)

        mainLayout.addLayout(btnLayout)

        self.setWindowTitle("Annotate Image")
        self.setMinimumWidth(100)
        self.setMinimumHeight(100)
        self.setGeometry(0, 0, 640, 640)
        restoreGeom(self, "addon_image_editor")
        if not self.close_queued:
            # When image isn't selected js side
            self.show()

    def check_changed(self, state: int):
        set_config("replace_all", bool(state), hidden=True)

    def discard(self):
        self.close_queued = True
        self.close()

    def save(self):
        self.close_queued = True
        self.web.eval("ankiAddonSaveImg()")

    def reset(self):
        self.load_img()
    
    def export_png(self):
        """触发 PNG 导出"""
        self.web.eval("document.getElementById('tool_export').click()")

    def on_bridge_cmd(self, cmd):
        if cmd == "img_src":
            if not self.create_new:
                self.load_img()

        elif cmd.startswith("svg_save:"):
            if self.create_new:
                svg_str = cmd[len("svg_save:") :]
                self.create_svg(svg_str)
            else:
                svg_str = cmd[len("svg_save:") :]
                self.save_svg(svg_str)
                
        elif cmd.startswith("png_save:"):
            self.save_png(cmd[len("png_save:") :])

    def check_editor_image_selected(self):
        self.editor_wv.evalWithCallback(
            "addonAnno.imageIsSelected()",
            lambda selected: (
                setattr(self, 'close_queued', True),
                self.close(),
                tooltip("Image wasn't selected properly.\nPlease try again.")
            ) if not selected else None
        )

    def load_img(self):
        """现代化的图像加载 - 带完整错误处理"""
        try:
            if not self.image_path or not self.image_path.exists():
                showWarning("图像文件不存在", parent=self.editor.widget)
                return
                
            img_path_str = self.image_path.resolve().as_posix()
            img_format = img_path_str.split(".")[-1].lower()
            
            if img_format not in MIME_TYPE:
                showWarning(f"不支持的图像格式: {img_format}", parent=self.editor.widget)
                return

            if img_format == "svg":
                try:
                    svg_content = self.image_path.read_text(encoding="utf-8")
                    img_data = json.dumps(svg_content)
                except UnicodeDecodeError:
                    showWarning("SVG文件编码错误", parent=self.editor.widget)
                    return
                except Exception as e:
                    showWarning(f"读取SVG文件失败: {str(e)}", parent=self.editor.widget)
                    return
            else:
                try:
                    mime_str = MIME_TYPE[img_format]
                    encoded_img_data = base64.b64encode(self.image_path.read_bytes()).decode()
                    img_data = f"'data:{mime_str};base64,{encoded_img_data}'"
                except Exception as e:
                    showWarning(f"读取图像文件失败: {str(e)}", parent=self.editor.widget)
                    return
                    
            # 安全的JavaScript执行
            js_code = f"ankiAddonSetImg({img_data}, '{img_format}')"
            self.web.eval(js_code)
            
        except Exception as e:
            showWarning(f"加载图像失败: {str(e)}", parent=self.editor.widget)

    def create_svg(self, svg_str):
        """现代化的SVG创建 - 使用CollectionOp"""
        try:
            if not mw.col:
                showWarning("集合未加载")
                return
                
            def create_op(col: Collection) -> OpChanges:
                # 现代化媒体写入
                new_name = col.media.write_data(
                    "svg_drawing.svg", svg_str.encode("utf-8")
                )
                
                # 安全的JavaScript执行
                img_el = f'"<img src=\\"{new_name}\\">"'
                write_image_script = f"document.execCommand('inserthtml', false, {img_el});"
                
                # 使用回调更新UI
                def update_ui():
                    self.create_new = False
                    self.image_path = Path(col.media.dir()) / new_name
                    tooltip("图像已创建", parent=self.editor.widget)
                    if self.close_queued:
                        self.close()
                
                # 使用TaskManager在主线程执行UI更新
                mw.taskman.run_on_main(update_ui)
                
                # 在主线程执行JavaScript
                mw.taskman.run_on_main(
                    lambda: self.editor_wv.evalWithCallback(
                        write_image_script,
                        lambda res: not res and self.editor_wv.eval(
                            "focusField(0); setTimeout(() => {" + write_image_script + "},25)"
                        )
                    )
                )
                
                return OpChanges()
            
            CollectionOp(
                parent=self,
                op=create_op
            ).success(
                lambda changes: None  # UI更新已在op中处理
            ).failure(
                lambda exc: showWarning(f"创建图像失败: {str(exc)}")
            ).run_in_background()
            
        except Exception as e:
            showWarning(f"创建SVG失败: {str(e)}")

    def save_svg(self, svg_str):
        """现代化的SVG保存 - 使用CollectionOp"""
        try:
            if not mw.col:
                showWarning("集合未加载")
                return
                
            image_path = self.image_path.resolve().as_posix()
            img_name = self.image_name
            base_name = ".".join(img_name.split(".")[:-1])[:15]
            desired_name = f"{base_name}.svg".replace(" ", "").replace('"', "").replace("$", "") or "blank.svg"
                
            # 现代化媒体写入
            new_name = mw.col.media.write_data(desired_name, svg_str.encode("utf-8"))
            
            if self.replaceAll.checkState() == Qt.CheckState.Checked:
                if self.editor.addMode:
                    self.replace_img_src_webview(new_name, replace_all=True)
                    self.replace_all_img_src_modern(img_name, new_name)
                else:
                    def save_and_replace(col: Collection) -> OpChanges:
                        if hasattr(self.editor, 'saveNow'):
                            self.editor.saveNow(lambda: None)
                        return self.replace_all_img_src_operation(col, img_name, new_name)
                    
                    CollectionOp(
                        parent=self,
                        op=save_and_replace
                    ).success(
                        lambda changes: self.on_replace_success(changes, new_name)
                    ).failure(
                        lambda exc: showWarning(f"保存失败: {str(exc)}")
                    ).run_in_background()
            else:
                self.replace_img_src_webview(new_name)
                tooltip("图像已保存", parent=self.editor.widget)
                
        except Exception as e:
            showWarning(f"保存SVG失败: {str(e)}")
            
        if self.close_queued:
            self.close()

    def replace_img_src_webview(self, name: str, replace_all=False):
        """安全的图像源替换 - WebView中"""
        try:
            if not name:
                showWarning("无效的图像名称")
                return
                
            namestr = base64.b64encode(str(name).encode("utf-8")).decode("ascii")
            
            if replace_all:
                js_code = f"addonAnno.changeAllSrc('{namestr}')"
            else:
                js_code = f"addonAnno.changeSrc('{namestr}')"
                
            self.editor_wv.eval(js_code)
            
        except Exception as e:
            showWarning(f"替换图像源失败: {str(e)}")

    def ask_on_close(self, evt):
        """询问用户是否保存更改"""
        opts = ["Cancel", "Discard", "Save"]
        diag = askUserDialog("Discard Changes?", opts, parent=self)
        diag.setDefault(0)
        ret = diag.run()
        if ret == opts[0]:
            evt.ignore()
        elif ret == opts[1]:
            saveGeom(self, "addon_image_editor")
            evt.accept()
        elif ret == opts[2]:
            self.save()
            saveGeom(self, "addon_image_editor")
            evt.ignore()

    def replace_all_img_src_modern(self, orig_name: str, new_name: str):
        """现代化的批量替换 - 使用CollectionOp"""
        def replace_op(col: Collection) -> OpChangesWithCount:
            return self.replace_all_img_src_operation(col, orig_name, new_name)
            
        CollectionOp(
            parent=self,
            op=replace_op
        ).success(
            lambda changes: self.on_replace_success(changes, new_name)
        ).failure(
            lambda exc: showWarning(f"批量替换失败: {str(exc)}")
        ).run_in_background()
        
    def on_replace_success(self, changes: OpChangesWithCount, new_name: str):
        tooltip(f"已修改 {getattr(changes, 'count', 0)} 个笔记中的图像", parent=self.editor.widget)

    def replace_all_img_src_operation(self, col: Collection, orig_name: str, new_name: str) -> OpChangesWithCount:
        """现代化的批量替换操作 - CollectionOp内部执行"""
        try:
            # 创建单一撤销点
            pos = col.add_custom_undo_entry("批量图像替换")
            
            # re.escape isn't compatible with rust regex
            to_escape = r"\.+*?()|[]{}^$#&-~"
            orig_name = "".join(f"\\{char}" if char in to_escape else char for char in orig_name)
            
            # 搜索包含图片的笔记
            n = col.find_notes("<img")
            
            # 构建正则表达式
            img_regs = [
                rf'(?P<first><img[^>]* src=)(?:"{orig_name}")|(?:\'{orig_name}\')(?P<second>[^>]*>)'
            ]
            if " " not in orig_name:
                img_regs.append(rf'(?P<first><img[^>]* src=){orig_name}(?P<second>(?: [^>]*>)|>)')
            
            repl = f'${{first}}"{new_name}"${{second}}'
            
            replaced_cnt = 0
            for reg in img_regs:
                res = col.find_and_replace(
                    note_ids=n,
                    search=reg,
                    replacement=repl,
                    regex=True,
                    match_case=False,
                    field_name=None,
                )
                replaced_cnt += res.count
                
            # 合并撤销点并返回结果
            result = OpChangesWithCount()
            result.CopyFrom(col.merge_undo_entries(pos))
            result.count = replaced_cnt
            return result
            
        except Exception as e:
            raise AnkiException(f"批量替换失败: {str(e)}")
    
    def save_png(self, png_data_uri):
        """保存 PNG 图像并替换当前编辑的图像"""
        try:
            if not mw.col:
                showWarning("集合未加载")
                return
            
            if not png_data_uri.startswith("data:image/png;base64,"):
                showWarning("无效的 PNG 数据格式")
                return
            
            png_binary = base64.b64decode(png_data_uri.split(",", 1)[1])
            
            # 生成文件名
            if hasattr(self, 'image_name') and self.image_name:
                base_name = self.image_name.rsplit('.', 1)[0][:15]
                base_name = base_name.replace(" ", "_").replace('"', "").replace("$", "")
                desired_name = f"{base_name}_exported.png"
            else:
                import time
                desired_name = f"image_export_{int(time.time())}.png"
            
            # 保存到媒体文件夹
            new_name = mw.col.media.write_data(desired_name, png_binary)
            
            # 更新编辑器中的图像
            if not self.create_new:
                if self.replaceAll.checkState() == Qt.CheckState.Checked:
                    self.replace_all_img_src_modern(self.image_name, new_name)
                else:
                    self.replace_img_src_webview(new_name)
            else:
                self.editor_wv.eval(f'document.execCommand("inserthtml", false, "<img src=\\"{new_name}\\">");')
            
            tooltip(f"PNG 图像已保存: {new_name}")
            self.close_queued = True
            self.close()
            
        except Exception as e:
            showWarning(f"保存 PNG 失败: {str(e)}")
