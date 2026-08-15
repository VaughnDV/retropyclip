import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const SERVICE_NAME = 'io.github.VaughnDV.RetroPyClip';
const OBJECT_PATH = '/io/github/VaughnDV/RetroPyClip';
const INTERFACE_NAME = SERVICE_NAME;
const CONCEALED_MIME_TYPE = 'x-kde-passwordManagerHint';

export default class RetroPyClipClipboardBridge extends Extension {
    enable() {
        this._enabled = true;
        this._reading = false;
        this._sending = false;
        this._serviceAvailable = false;
        this._lastDeliveredText = null;
        this._clipboard = St.Clipboard.get_default();
        this._selection = Shell.Global.get().get_display().get_selection();
        this._selectionOwnerChangedId = this._selection.connect(
            'owner-changed',
            (_selection, selectionType) => {
                if (selectionType === Meta.SelectionType.SELECTION_CLIPBOARD)
                    this._checkClipboard();
            },
        );
        this._serviceWatchId = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            SERVICE_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => {
                this._serviceAvailable = true;
                this._lastDeliveredText = null;
                this._checkClipboard();
            },
            () => {
                this._serviceAvailable = false;
            },
        );
        this._checkClipboard();
    }

    disable() {
        this._enabled = false;
        if (this._selectionOwnerChangedId) {
            this._selection.disconnect(this._selectionOwnerChangedId);
            this._selectionOwnerChangedId = 0;
        }
        if (this._serviceWatchId) {
            Gio.bus_unwatch_name(this._serviceWatchId);
            this._serviceWatchId = 0;
        }
        this._selection = null;
        this._clipboard = null;
    }

    _checkClipboard() {
        if (!this._enabled || !this._serviceAvailable || this._reading || this._sending)
            return;
        if (
            this._clipboard
                .get_mimetypes(St.ClipboardType.CLIPBOARD)
                .includes(CONCEALED_MIME_TYPE)
        )
            return;
        this._reading = true;
        this._clipboard.get_text(St.ClipboardType.CLIPBOARD, (_clipboard, text) => {
            this._reading = false;
            if (!this._enabled || !text || text === this._lastDeliveredText)
                return;
            this._sendText(text);
        });
    }

    _sendText(text) {
        this._sending = true;
        Gio.DBus.session.call(
            SERVICE_NAME,
            OBJECT_PATH,
            INTERFACE_NAME,
            'CaptureText',
            new GLib.Variant('(s)', [text]),
            null,
            Gio.DBusCallFlags.NO_AUTO_START,
            1000,
            null,
            (connection, result) => {
                this._sending = false;
                if (!this._enabled)
                    return;
                try {
                    connection.call_finish(result);
                    this._lastDeliveredText = text;
                    this._checkClipboard();
                } catch (error) {
                    console.error(`RetroPyClip clipboard delivery failed: ${error.message}`);
                }
            },
        );
    }
}
