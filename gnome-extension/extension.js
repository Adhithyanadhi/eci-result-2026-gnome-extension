import GObject from 'gi://GObject';
import St from 'gi://St';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Clutter from 'gi://Clutter';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

const REFRESH_SECONDS = 5;

// Fixed top-bar positions:
// 0th value = TVK
// 1st value = ADMK
// 2nd value = DMK
//
// Each value is:
// won/leading
const ORDER = ['TVK', 'ADMK', 'DMK'];

const EciSeatShareIndicator = GObject.registerClass(
class EciSeatShareIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'ECI Seat Share');

        this._label = new St.Label({
            text: '--/--  --/--  --/--',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'eci-seat-share-label',
        });

        this.add_child(this._label);
    }

    setText(text) {
        this._label.set_text(text);
    }
});

export default class EciSeatShareExtension extends Extension {
    enable() {
        this._indicator = new EciSeatShareIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');

        this._refresh();

        this._timeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            REFRESH_SECONDS,
            () => {
                this._refresh();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    disable() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = null;
        }

        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }

    _cachePath() {
        return GLib.build_filenamev([
            GLib.get_user_cache_dir(),
            'eci-seat-share.json',
        ]);
    }

    _readTextFile(path) {
        const file = Gio.File.new_for_path(path);

        if (!file.query_exists(null))
            return null;

        const [ok, contents] = file.load_contents(null);
        if (!ok)
            return null;

        return new TextDecoder('utf-8').decode(contents);
    }

    _displayFromPayload(payload) {
        if (payload.topbar_values && Array.isArray(payload.topbar_values)) {
            const values = payload.topbar_values.slice(0, 3);
            while (values.length < 3)
                values.push('--/--');

            const suffix = payload.has_error || payload.has_stale ? ' *' : '';
            return values.join('  ') + suffix;
        }

        const parties = payload.parties || {};
        const values = ORDER.map((party) => {
            const item = parties[party];
            if (!item)
                return '0/0';

            const won = Number(item.won || 0);
            const leading = Number(
                item.leading !== undefined
                    ? item.leading
                    : Math.max(0, Number(item.seats || 0) - won)
            );

            return `${won}/${leading}`;
        });

        const suffix = payload.has_error || payload.has_stale ? ' *' : '';
        return values.join('  ') + suffix;
    }

    _refresh() {
        if (!this._indicator)
            return;

        try {
            const text = this._readTextFile(this._cachePath());
            if (!text) {
                this._indicator.setText('--/--  --/--  --/--');
                return;
            }

            const payload = JSON.parse(text);
            this._indicator.setText(this._displayFromPayload(payload));
        } catch (error) {
            console.error(`ECI Seat Share error: ${error}`);
            this._indicator.setText('ECI error');
        }
    }
}
