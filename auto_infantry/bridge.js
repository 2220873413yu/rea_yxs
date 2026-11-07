'use strict';

const lua = Process.getModuleByName('libtolua.so');
const getTop = new NativeFunction(lua.getExportByName('lua_gettop'), 'int', ['pointer']);
const setTop = new NativeFunction(lua.getExportByName('lua_settop'), 'void', ['pointer', 'int']);
const load = new NativeFunction(lua.getExportByName('luaL_loadbuffer'), 'int',
    ['pointer', 'pointer', 'ulong', 'pointer']);
const pcall = new NativeFunction(lua.getExportByName('lua_pcall'), 'int',
    ['pointer', 'int', 'int', 'int']);
const toString = new NativeFunction(lua.getExportByName('lua_tolstring'), 'pointer',
    ['pointer', 'int', 'pointer']);
const pending = [];
let running = false;
let updateCount = 0;
const threadNames = new Map();
let enabled = false;
let trainingSpeedEnabled = false;
let allowedUnits = new Set();
let heroEnabled = false;
let heroEpoch = 0;
let allowedHeroes = new Set();
let collectEnabled = false;
let collectEpoch = 0;
let huntEnabled = false;
let huntEpoch = 0;
let leagueEnabled = false;
let leagueEpoch = 0;
let beaconEnabled = false;
let beaconEpoch = 0;

/** Copy one Lua result without retaining pointers into the game's Lua heap. */
function readString(state, index) {
    const length = Memory.alloc(Process.pointerSize);
    length.writeU64(0);
    const value = toString(state, index, length);
    if (value.isNull()) return '';
    const bytes = Number(length.readU64());
    if (bytes > 128 * 1024) throw new Error('Lua result exceeds 128 KiB');
    return value.readUtf8String(bytes);
}

/** Execute one queued operation on the existing Lua update thread and restore its stack. */
function execute(state, task) {
    if ((task.spending === 'beacon' && (!beaconEnabled || task.beaconEpoch !== beaconEpoch)) ||
        (task.spending === 'league' && (!leagueEnabled || task.leagueEpoch !== leagueEpoch)) ||
        (task.spending === 'hunt' && (!huntEnabled || task.huntEpoch !== huntEpoch)) ||
        (task.spending === 'hero' && (!heroEnabled || task.heroEpoch !== heroEpoch || !allowedHeroes.has(task.unit))) ||
        (task.spending === 'collect' && (!collectEnabled || task.collectEpoch !== collectEpoch)) ||
        ((task.spending === true || task.spending === 'train_speed') &&
            (!enabled || !allowedUnits.has(task.unit) || (task.spending === 'train_speed' && !trainingSpeedEnabled)))) {
        clearTimeout(task.timer);
        task.reject(new Error('Automatic training is switched off'));
        return;
    }
    const oldTop = getTop(state);
    try {
        const source = Memory.allocUtf8String(task.source);
        const chunk = Memory.allocUtf8String('@rea-auto-infantry');
        const size = unescape(encodeURIComponent(task.source)).length;
        if (load(state, source, size, chunk) !== 0) throw new Error(readString(state, -1));
        if (pcall(state, 0, 1, 0) !== 0) throw new Error(readString(state, -1));
        task.resolve(readString(state, -1));
    } catch (error) {
        task.reject(new Error(String(error)));
    } finally {
        setTop(state, oldTop);
        clearTimeout(task.timer);
    }
}

const hook = Interceptor.attach(lua.getExportByName('lua_pcall'), {
    onEnter(args) {
        this.luaState = args[0];
    },
    onLeave() {
        updateCount++;
        if (running || pending.length === 0) return;
        if (!threadNames.has(this.threadId)) {
            try {
                threadNames.set(this.threadId,
                    File.readAllText('/proc/self/task/' + this.threadId + '/comm').trim());
            } catch (_) { threadNames.set(this.threadId, 'unknown'); }
        }
        if (threadNames.get(this.threadId) !== 'UnityMain') return;
        const task = pending.shift();
        running = true;
        try { execute(this.luaState, task); } finally { running = false; }
    }
});

rpc.exports = {
    /** Expose hook activity for diagnosing scheduling without executing Lua. */
    status() { return {updateCount, queued: pending.length}; },
    /** Enqueue a bounded caller-owned Lua operation; no work survives a timed-out queue item. */
    query(source, spending = false, unit = 411, expectedHeroEpoch = null) {
        // Frida may marshal omitted RPC arguments as null rather than undefined.
        spending = spending == null ? false : spending;
        unit = unit == null ? 411 : unit;
        if (typeof source !== 'string' || source.length > 32000) throw new Error('Invalid Lua source');
        if (![false, true, 'train_speed', 'hero', 'collect', 'hunt', 'league', 'beacon'].includes(spending)) throw new Error('Invalid spending category');
        if ((spending === true || spending === 'train_speed') && ![411, 412, 413, 803].includes(unit)) throw new Error('Unsupported troop identifier');
        if ((spending === 'hero' || spending === 'collect' || spending === 'hunt' || spending === 'league' || spending === 'beacon') && (!Number.isInteger(unit) || unit <= 0 || unit > 10000000)) throw new Error('Unsupported hero');
        if (pending.length >= 8) throw new Error('Lua queue is full');
        return new Promise((resolve, reject) => {
            const task = {source, spending, unit,
                heroEpoch: expectedHeroEpoch === null ? heroEpoch : expectedHeroEpoch,
                collectEpoch: expectedHeroEpoch === null ? collectEpoch : expectedHeroEpoch,
                huntEpoch: expectedHeroEpoch === null ? huntEpoch : expectedHeroEpoch,
                leagueEpoch: expectedHeroEpoch === null ? leagueEpoch : expectedHeroEpoch,
                beaconEpoch: expectedHeroEpoch === null ? beaconEpoch : expectedHeroEpoch,
                resolve, reject, timer: null};
            task.timer = setTimeout(() => {
                const index = pending.indexOf(task);
                if (index !== -1) {
                    pending.splice(index, 1);
                    reject(new Error('Game Lua update did not run within five seconds'));
                }
            }, 5000);
            pending.push(task);
        });
    },
    /** Disable spending immediately, including operations still waiting for the next game callback. */
    setenabled(value, units = [411], useTrainingSpeed = false) {
        if (!Array.isArray(units) || units.some(u => ![411, 412, 413, 803].includes(u))) throw new Error('Invalid troop selection');
        if (value === true && units.length === 0) throw new Error('No troops selected');
        enabled = value === true;
        trainingSpeedEnabled = enabled && useTrainingSpeed === true;
        allowedUnits = new Set(enabled ? units : []);
        {
            for (let i = pending.length - 1; i >= 0; i--) {
                if ((pending[i].spending === true || pending[i].spending === 'train_speed') &&
                    (!enabled || !allowedUnits.has(pending[i].unit) || (pending[i].spending === 'train_speed' && !trainingSpeedEnabled))) {
                    const task = pending.splice(i, 1)[0];
                    clearTimeout(task.timer);
                    task.reject(new Error('Automatic training is switched off'));
                }
            }
        }
        return enabled;
    },
    /** Independently revoke queued recovery commands, including across an off/on transition. */
    setheroenabled(value, heroes = []) {
        if (!Array.isArray(heroes) || heroes.length > 1000 ||
            heroes.some(id => !Number.isInteger(id) || id <= 0 || id > 10000000)) throw new Error('Invalid hero selection');
        if (value === true && heroes.length === 0) throw new Error('No heroes selected');
        heroEnabled = value === true;
        allowedHeroes = new Set(heroEnabled ? heroes : []);
        heroEpoch++;
        for (let i = pending.length - 1; i >= 0; i--) {
            if (pending[i].spending === 'hero') {
                const task = pending.splice(i, 1)[0];
                clearTimeout(task.timer);
                task.reject(new Error('Hero recovery switch changed'));
            }
        }
        return heroEpoch;
    },
    /** Independently cancel queued collection departures across stop/start transitions. */
    setcollectenabled(value) {
        collectEnabled = value === true;
        collectEpoch++;
        for (let i = pending.length - 1; i >= 0; i--) {
            if (pending[i].spending === 'collect') {
                const task = pending.splice(i, 1)[0];
                clearTimeout(task.timer);
                task.reject(new Error('Collection switch changed'));
            }
        }
        return collectEpoch;
    },
    /** Revoke both hunting departures and quick-combat commands independently of other features. */
    sethuntenabled(value) {
        huntEnabled = value === true;
        huntEpoch++;
        for (let i = pending.length - 1; i >= 0; i--) {
            if (pending[i].spending === 'hunt') {
                const task = pending.splice(i, 1)[0];
                clearTimeout(task.timer);
                task.reject(new Error('Hunt switch changed'));
            }
        }
        return huntEpoch;
    },
    /** Cancel only alliance mining departures, including stale commands across an off/on transition. */
    setleagueenabled(value) {
        leagueEnabled = value === true;
        leagueEpoch++;
        for (let i = pending.length - 1; i >= 0; i--) {
            if (pending[i].spending === 'league') {
                const task = pending.splice(i, 1)[0];
                clearTimeout(task.timer);
                task.reject(new Error('Alliance collection switch changed'));
            }
        }
        return leagueEpoch;
    },
    /** Revoke beacon departure/recall/claim and candidate reads independently across switch generations. */
    setbeaconenabled(value) {
        beaconEnabled = value === true;
        beaconEpoch++;
        for (let i = pending.length - 1; i >= 0; i--) {
            if (pending[i].spending === 'beacon') {
                const task = pending.splice(i, 1)[0];
                clearTimeout(task.timer);
                task.reject(new Error('Beacon rescue switch changed'));
            }
        }
        return beaconEpoch;
    },
    /** Disable the hook and reject queued commands before caller detach. */
    close() {
        enabled = false;
        trainingSpeedEnabled = false;
        heroEnabled = false;
        allowedHeroes.clear();
        collectEnabled = false;
        huntEnabled = false;
        leagueEnabled = false;
        beaconEnabled = false;
        beaconEpoch++;
        leagueEpoch++;
        huntEpoch++;
        collectEpoch++;
        heroEpoch++;
        allowedUnits.clear();
        hook.detach();
        for (const task of pending.splice(0)) {
            clearTimeout(task.timer);
            task.reject(new Error('Bridge closed'));
        }
    }
};
