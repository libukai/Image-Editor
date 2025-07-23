import os
from pathlib import Path

import anki
from anki import version as ANKIVER
from anki.notes import Note
from anki.collection import Collection
from anki.errors import AnkiException
from aqt import mw, gui_hooks
from aqt.editor import EditorWebView, Editor
from aqt.utils import tooltip, showWarning
from aqt.qt import QMenu, QT_VERSION_STR
from aqt.operations import CollectionOp

from .annotation import AnnotateDialog

ADDON_PACKAGE = mw.addonManager.addonFromModule(__name__)
ICONS_PATH = os.path.join(os.path.dirname(__file__), "icons")
QT6 = QT_VERSION_STR.split(".")[0] == "6"

def open_annotate_window(editor, name="", path="", src="", create_new=False):
    """安全地打开图像编辑对话框"""
    try:
        if not mw.col:
            showWarning("集合未加载，无法编辑图像")
            return
            
        mw.annodial = AnnotateDialog(
            editor, name=name, path=path, src=src, create_new=create_new)
    except Exception as e:
        showWarning(f"打开图像编辑器失败: {str(e)}")


def add_context_menu_action(wv: EditorWebView, m: QMenu):
    """现代化的上下文菜单处理"""
    try:
        if not mw.col:
            return
            
        if QT6:
            context_data = wv.lastContextMenuRequest()
        else:
            context_data = wv.page().contextMenuData()
            
        url = context_data.mediaUrl()
        if not url.isValid():
            return
            
        image_name = url.fileName()
        image_path = Path(mw.col.media.dir()) / image_name
        
        if image_path.is_file():
            a = m.addAction("Edit Image")
            a.triggered.connect(lambda _, path=image_path, nm=image_name: open_annotate_window(
                wv.editor, name=nm, path=path, src=url.toString()))
    except Exception as e:
        tooltip(f"添加编辑菜单失败: {str(e)}")


def insert_js(web_content, context):
    if not isinstance(context, Editor):
        return
    web_content.js.append(f"/_addons/{ADDON_PACKAGE}/web/editor.js")


def setup_editor_buttons(btns, editor):
    """设置编辑器按钮 - 现代化版本"""
    try:
        hotkey = "Ctrl + Shift + I"
        icon = os.path.join(ICONS_PATH, "draw.svg")
        
        b = editor.addButton(
            icon, 
            "Draw Image",
            lambda o=editor: open_annotate_window(o, create_new=True),
            tip=f"({hotkey})",
            keys=hotkey, 
            disables=True
        )
        btns.append(b)
    except Exception as e:
        tooltip(f"添加编辑按钮失败: {str(e)}")
        
    return btns


def on_editor_note_load(js: str, note: Note, editor: Editor):
    """编辑器笔记加载时的 JavaScript 注入"""
    try:
        js += "\naddonAnno.addListener();"
    except Exception as e:
        tooltip(f"加载编辑器脚本失败: {str(e)}")
    return js


def on_config():
    tooltip("This addon does not have user-editable config")


# 现代化钩子注册 - 使用 gui_hooks
def setup_hooks():
    """设置所有钩子 - 现代 gui_hooks 系统"""
    try:
        # 使用正确的钩子名称
        gui_hooks.editor_will_show_context_menu.append(add_context_menu_action)
        gui_hooks.editor_did_init_buttons.append(setup_editor_buttons)
        gui_hooks.webview_will_set_content.append(insert_js)
        gui_hooks.editor_will_load_note.append(on_editor_note_load)
    except Exception as e:
        showWarning(f"设置钩子失败: {str(e)}")

# 插件初始化
mw.addonManager.setWebExports(__name__, r"web/editor.js")
mw.addonManager.setConfigAction(__name__, on_config)
setup_hooks()
