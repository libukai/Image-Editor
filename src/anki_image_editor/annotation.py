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
        # 触发导出 - 模拟点击菜单项
        self.web.eval("""
            console.log('Export button clicked');
            
            // 尝试多种方式访问 svgCanvas
            var canvas = window.svgCanvas || svgCanvas || (editor && editor.canvas);
            
            if (canvas) {
                console.log('Canvas found:', canvas);
                
                // 直接调用导出功能 - 模拟菜单点击
                var exportMenuItem = document.getElementById('tool_export');
                if (exportMenuItem) {
                    console.log('Clicking export menu item');
                    exportMenuItem.click();
                } else {
                    console.log('Export menu item not found, trying direct call');
                    // 如果找不到菜单项，尝试直接调用
                    if (typeof canvas.rasterExport === 'function') {
                        canvas.rasterExport();
                    } else {
                        console.error('rasterExport function not found');
                    }
                }
            } else {
                console.log('Canvas not found in any location');
                console.log('window.svgCanvas:', window.svgCanvas);
                console.log('typeof svgCanvas:', typeof svgCanvas);
                console.log('editor:', typeof editor !== 'undefined' ? editor : 'undefined');
            }
        """)

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
            png_data = cmd[len("png_save:") :]
            tooltip(f"收到 PNG 数据，长度: {len(png_data)}")
            self.save_png(png_data)

    def check_editor_image_selected(self):
        def check_image_selected(selected):
            if selected == False:
                self.close_queued = True
                self.close()
                tooltip("Image wasn't selected properly.\nPlease try again.")

        # Check if image is properly selected
        self.editor_wv.evalWithCallback(
            "addonAnno.imageIsSelected()", check_image_selected
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
            desired_name = ".".join(img_name.split(".")[:-1])
            desired_name = desired_name[:15] if len(desired_name) > 15 else desired_name
            desired_name += ".svg"
            # remove whitespace and double quote as it messes with replace_all_img_src
            desired_name = desired_name.replace(" ", "").replace('"', "").replace("$", "")
            if not desired_name:
                desired_name = "blank"
                
            # 现代化媒体写入
            new_name = mw.col.media.write_data(desired_name, svg_str.encode("utf-8"))
            
            if self.replaceAll.checkState() == Qt.CheckState.Checked:
                if self.editor.addMode:
                    self.replace_img_src_webview(new_name, replace_all=True)
                    self.replace_all_img_src_modern(img_name, new_name)
                else:
                    # 现代化保存模式
                    def save_and_replace(col: Collection) -> OpChanges:
                        # 保存编辑器内容
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
        """替换成功回调"""
        count = getattr(changes, 'count', 0)
        tooltip(f"已修改 {count} 个笔记中的图像", parent=self.editor.widget)

    def replace_all_img_src_operation(self, col: Collection, orig_name: str, new_name: str) -> OpChangesWithCount:
        """现代化的批量替换操作 - CollectionOp内部执行"""
        try:
            # 创建单一撤销点
            pos = col.add_custom_undo_entry("批量图像替换")
            
            # re.escape isn't compatible with rust regex
            to_escape = r"\.+*?()|[]{}^$#&-~"
            escaped_name = ""
            for i, char in enumerate(orig_name):
                if char in to_escape:
                    escaped_name += "\\"
                escaped_name += char
            orig_name = escaped_name
            
            # 现代化搜索
            n = col.find_notes("<img")
            
            # src element quoted case
            reg1 = r"""(?P<first><img[^>]* src=)(?:"{name}")|(?:'{name}')(?P<second>[^>]*>)""".format(
                name=orig_name
            )
            # unquoted case
            reg2 = r"""(?P<first><img[^>]* src=){name}(?P<second>(?: [^>]*>)|>)""".format(
                name=orig_name
            )
            img_regs = [reg1]
            if " " not in orig_name:
                img_regs.append(reg2)
            
            repl = """${first}"%s"${second}""" % new_name
            
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
                
            # 合并撤销点
            changes = col.merge_undo_entries(pos)
            # 创建带计数的结果
            result = OpChangesWithCount()
            result.CopyFrom(changes)
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
            
            # 解析 data URI
            # 格式: data:image/png;base64,iVBORw0KGgoAAAA...
            if not png_data_uri.startswith("data:image/png;base64,"):
                showWarning("无效的 PNG 数据格式")
                return
            
            # 提取 base64 数据
            base64_data = png_data_uri.split(",", 1)[1]
            
            # 解码 base64 为二进制数据
            png_binary = base64.b64decode(base64_data)
            
            # 生成文件名
            if hasattr(self, 'image_name') and self.image_name:
                # 基于原文件名生成新文件名
                base_name = self.image_name.rsplit('.', 1)[0]
                base_name = base_name[:15] if len(base_name) > 15 else base_name
                # 清理文件名
                base_name = base_name.replace(" ", "_").replace('"', "").replace("$", "")
                desired_name = f"{base_name}_exported.png"
            else:
                # 使用时间戳生成唯一文件名
                import time
                timestamp = int(time.time())
                desired_name = f"image_export_{timestamp}.png"
            
            # 保存到媒体文件夹
            new_name = mw.col.media.write_data(desired_name, png_binary)
            
            # 更新编辑器中的图像
            if not self.create_new:
                # 替换现有图像
                if self.replaceAll.checkState() == Qt.CheckState.Checked:
                    # 替换所有相同的图像
                    self.replace_all_img_src_modern(self.image_name, new_name)
                else:
                    # 只替换当前选中的图像
                    img_el_b64 = base64.b64encode(new_name.encode()).decode()
                    change_src_script = f"addonAnno.changeSrc('{img_el_b64}');"
                    self.editor_wv.eval(change_src_script)
            else:
                # 插入新图像
                img_el = f'"<img src=\\"{new_name}\\">"'
                write_image_script = f"document.execCommand('inserthtml', false, {img_el});"
                self.editor_wv.eval(write_image_script)
            
            # 显示成功消息
            tooltip(f"PNG 图像已保存: {new_name}")
            
            # 关闭编辑器
            self.close_queued = True
            self.close()
            
        except Exception as e:
            showWarning(f"保存 PNG 失败: {str(e)}")
