#!/usr/bin/env python3
"""Always-on-top desktop widget wrapper for timer.html, docked to the
bottom-right corner of the screen. Uses GTK + WebKitGTK (both ship with
Plasma) so no extra downloads are needed.

Force XWayland: under native Wayland, apps cannot position their own
window, which we need to dock to a corner.

I don't know if it would work on Windows. Maybe I will update it.
"""
import json
import os

os.environ.setdefault("GDK_BACKEND", "x11")
# NVIDIA's GBM support trips up WebKitGTK's hardware compositor
# ("Failed to create GBM buffer"), leaving the view blank; force software rendering.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timer.html")
MARGIN = 24
FALLBACK_SIZE = (420, 560)

# Tracks the window's fitted content size, so it can be re-docked to the
# corner any time it's shown again (restore from tray, session complete).
# "pending_timer" is GLib's own id for the session-end fallback (see
# schedule_session_end below); it lives outside the WebView on purpose.
state = {"width": FALLBACK_SIZE[0], "height": FALLBACK_SIZE[1], "pending_timer": None}


def place_bottom_right(win):
    display = Gdk.Display.get_default()
    gdk_window = win.get_window()
    monitor = (
        display.get_monitor_at_window(gdk_window)
        if gdk_window
        else display.get_monitor(0)
    )
    geo = monitor.get_workarea()
    x = geo.x + geo.width - state["width"] - MARGIN
    y = geo.y + geo.height - state["height"] - MARGIN
    win.move(x, y)


def main():
    win = Gtk.Window()
    win.set_title("Deep Work Timer")
    win.set_decorated(False)
    win.set_keep_above(True)
    win.set_skip_taskbar_hint(True)
    win.set_skip_pager_hint(True)
    win.stick()
    win.set_default_size(*FALLBACK_SIZE)

    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual and screen.is_composited():
        win.set_visual(visual)
    win.set_app_paintable(True)

    webview = WebKit2.WebView()
    webview.set_background_color(Gdk.RGBA(0, 0, 0, 0))
    webview.connect("context-menu", lambda *a: True)  # no right-click menu
    webview.load_uri("file://" + HTML_PATH)

    win.add(webview)

    def show_window(*_a):
        win.show_all()
        win.set_keep_above(True)
        win.present()
        place_bottom_right(win)

    def minimize_to_tray(*_a):
        win.hide()

    def quit_app(*_a):
        Gtk.main_quit()

    def quit_on_escape(_widget, event):
        if event.keyval == Gdk.KEY_Escape or (
            event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_q
        ):
            quit_app()

    win.connect("key-press-event", quit_on_escape)
    win.connect("destroy", quit_app)

    # --- system tray icon ---
    tray = Gtk.StatusIcon()
    tray.set_from_icon_name("preferences-system-time")
    tray.set_tooltip_text("Deep Work Timer")
    tray.connect("activate", show_window)

    tray_menu = Gtk.Menu()
    show_item = Gtk.MenuItem(label="Show Timer")
    show_item.connect("activate", show_window)
    quit_item = Gtk.MenuItem(label="Quit")
    quit_item.connect("activate", quit_app)
    tray_menu.append(show_item)
    tray_menu.append(quit_item)
    tray_menu.show_all()

    def on_tray_popup_menu(icon, button, activate_time):
        tray_menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    tray.connect("popup-menu", on_tray_popup_menu)

    # --- JS <-> Python bridge (minimize / close / session-complete buttons) ---
    # WebKit throttles JS timers in a hidden/occluded view to save power, so a
    # minimized session's own setInterval can't be trusted to pop the window
    # back up on time. Instead, Python schedules its own end-of-session timer
    # (GLib's main loop isn't affected by the WebView being hidden) and forces
    # the page to finish when it fires.
    def cancel_pending_timer():
        timer_id = state["pending_timer"]
        if timer_id is not None:
            GLib.source_remove(timer_id)
            state["pending_timer"] = None

    def schedule_session_end(duration_seconds):
        cancel_pending_timer()

        def on_due():
            state["pending_timer"] = None
            show_window()
            webview.evaluate_javascript("completeSession();", -1, None, None, None, None, None)
            return False

        # +2s buffer: if the window is visible, JS's own on-time completion
        # fires first and cancels this, so it's purely a safety net.
        state["pending_timer"] = GLib.timeout_add_seconds(int(duration_seconds) + 2, on_due)

    content_manager = webview.get_user_content_manager()
    content_manager.register_script_message_handler("app")

    def on_app_message(_manager, js_result):
        value = getattr(js_result, "get_js_value", lambda: js_result)()
        try:
            payload = json.loads(value.to_string())
        except (ValueError, TypeError):
            return
        action = payload.get("action")
        if action == "minimize":
            minimize_to_tray()
        elif action == "close":
            quit_app()
        elif action == "complete":
            cancel_pending_timer()
            show_window()
        elif action == "cancel":
            cancel_pending_timer()
        elif action == "start":
            schedule_session_end(payload.get("duration", 0))

    content_manager.connect("script-message-received::app", on_app_message)

    win.show_all()
    place_bottom_right(win)

    def fit_to_content(webview, load_event):
        if load_event != WebKit2.LoadEvent.FINISHED:
            return

        def apply_size(js_result=None, *_):
            script = "JSON.stringify(document.getElementById('app').getBoundingClientRect());"

            def on_result(wv, task, _data):
                try:
                    value = wv.evaluate_javascript_finish(task)
                    rect = json.loads(value.to_string())
                    width = round(rect["width"])
                    height = round(rect["height"])
                except Exception:
                    return
                if width < 50 or height < 50:
                    return
                state["width"] = width
                state["height"] = height
                geometry = Gdk.Geometry()
                geometry.min_width = width
                geometry.min_height = height
                geometry.max_width = width
                geometry.max_height = height
                win.set_geometry_hints(
                    None,
                    geometry,
                    Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE,
                )
                win.resize(width, height)
                place_bottom_right(win)
                GLib.timeout_add(50, lambda: place_bottom_right(win))

            webview.evaluate_javascript(script, -1, None, None, None, on_result, None)

        GLib.timeout_add(80, apply_size)

    webview.connect("load-changed", fit_to_content)

    Gtk.main()


if __name__ == "__main__":
    main()
