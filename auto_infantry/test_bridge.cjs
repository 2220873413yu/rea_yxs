/** Exercise independent gates and late-queued stale requests without loading Frida or a game. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

/** Provide only the native primitives necessary to run the production queue and spending gates. */
function bridge() {
    let callbacks;
    let loads = 0;
    const pointer = {isNull: () => false, readUtf8String: () => 'ok',
        writeU64() {}, readU64: () => 2};
    const context = {
        rpc: {exports: {}}, setTimeout, clearTimeout,
        Process: {pointerSize: 8, getModuleByName: () => ({getExportByName: name => name})},
        NativeFunction: function(name) {
            if (name === 'lua_tolstring') return () => pointer;
            if (name === 'luaL_loadbuffer') return () => { loads++; return 0; };
            return () => 0;
        },
        Memory: {alloc: () => pointer, allocUtf8String: () => pointer},
        File: {readAllText: () => 'UnityMain'},
        Interceptor: {attach: (name, hooks) => { callbacks = hooks; return {detach() {}}; }}
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(__dirname + '/bridge.js', 'utf8'), context);
    return {
        rpc: context.rpc.exports,
        drain() {
            const invocation = {threadId: 1};
            callbacks.onEnter.call(invocation, [pointer]);
            callbacks.onLeave.call(invocation);
        },
        loads: () => loads
    };
}

/** Check gate isolation, immediate cancellation and protection against rapid off/on transitions. */
async function main() {
    let b = bridge();
    let task = b.rpc.query('return "ok"', null, null);
    b.drain();
    assert.equal(await task, 'ok');
    b.rpc.close();

    b = bridge();
    assert.throws(() => b.rpc.setheroenabled(true, []), /No heroes selected/);
    let selectedEpoch = b.rpc.setheroenabled(true, [305, 315]);
    task = b.rpc.query('return "ok"', 'hero', 303, selectedEpoch);
    const unselected = assert.rejects(task, /switched off/);
    b.drain();
    await unselected;
    assert.equal(b.loads(), 0, 'An unselected owned hero must never reach Lua');
    task = b.rpc.query('return "ok"', 'hero', 305, selectedEpoch);
    b.drain();
    assert.equal(await task, 'ok');
    task = b.rpc.query('return "ok"', 'hero', 315, selectedEpoch);
    const changed = assert.rejects(task, /switch changed/);
    selectedEpoch = b.rpc.setheroenabled(true, [303]);
    await changed;
    b.rpc.close();

    b = bridge();
    const epoch = b.rpc.setheroenabled(true, [303]);
    b.rpc.setenabled(true, [411]);
    task = b.rpc.query('return "ok"', 'hero', 303, epoch);
    b.rpc.setenabled(false, []);
    b.drain();
    assert.equal(await task, 'ok', 'Troop-off must preserve recovery');
    b.rpc.setenabled(true, [411]);
    task = b.rpc.query('return "ok"', true, 411);
    b.rpc.setheroenabled(false);
    b.drain();
    assert.equal(await task, 'ok', 'Recovery-off must preserve troop work');
    b.rpc.close();

    b = bridge();
    const old = b.rpc.setheroenabled(true, [303]);
    task = b.rpc.query('return "ok"', 'hero', 303, old);
    const canceled = assert.rejects(task, /switch changed/);
    b.rpc.setheroenabled(false);
    await canceled;
    b.rpc.setheroenabled(true, [303]);
    // Simulate an old Python iteration enqueueing after the user has already restarted recovery.
    task = b.rpc.query('return "ok"', 'hero', 303, old);
    const stale = assert.rejects(task, /switched off/);
    b.drain();
    await stale;
    assert.equal(b.loads(), 0, 'Stale requests must never reach Lua');
    b.rpc.close();

    b = bridge();
    task = b.rpc.query('return "ok"', 'hero', 303, 0);
    const disabled = assert.rejects(task, /switched off/);
    b.drain();
    await disabled;
    assert.equal(b.loads(), 0, 'Startup defaults must prevent spending');
    b.rpc.close();
    b = bridge();
    const collect = b.rpc.setcollectenabled(true);
    task = b.rpc.query('return "ok"', 'collect', 305, collect);
    b.rpc.setheroenabled(false, []);
    b.drain();
    assert.equal(await task, 'ok', 'Normal recovery-off must not disable collection departures');
    task = b.rpc.query('return "ok"', 'collect', 305, collect);
    const collectCanceled = assert.rejects(task, /Collection switch changed/);
    b.rpc.setcollectenabled(false);
    await collectCanceled;
    b.rpc.setcollectenabled(true);
    task = b.rpc.query('return "ok"', 'collect', 305, collect);
    const oldDeparture = assert.rejects(task, /switched off/);
    b.drain();
    await oldDeparture;
    const normalGeneration = b.rpc.setheroenabled(true, [303]);
    task = b.rpc.query('return "ok"', 'hero', 303, normalGeneration);
    b.rpc.setcollectenabled(false);
    b.drain();
    assert.equal(await task, 'ok', 'Collection-off must preserve explicitly selected normal recovery');
    b.rpc.close();
    b = bridge();
    b.rpc.setenabled(true, [411]);
    task = b.rpc.query('return "ok"', 'train_speed', 411);
    const noItems = assert.rejects(task, /switched off/);
    b.drain();
    await noItems;
    assert.equal(b.loads(), 0, 'Default normal training must not authorize an item');
    task = b.rpc.query('return "ok"', true, 411);
    b.drain();
    assert.equal(await task, 'ok', 'Normal training remains authorized');
    b.rpc.setenabled(true, [411], true);
    task = b.rpc.query('return "ok"', 'train_speed', 411);
    b.drain();
    assert.equal(await task, 'ok');
    task = b.rpc.query('return "ok"', 'train_speed', 411);
    const speedCanceled = assert.rejects(task, /switched off/);
    b.rpc.setenabled(true, [411], false);
    await speedCanceled;
    b.rpc.close();
    b = bridge();
    let hunt = b.rpc.sethuntenabled(true);
    task = b.rpc.query('return "ok"', 'hunt', 303, hunt);
    const huntCanceled = assert.rejects(task, /Hunt switch changed/);
    b.rpc.sethuntenabled(false);
    await huntCanceled;
    b.rpc.sethuntenabled(true);
    task = b.rpc.query('return "ok"', 'hunt', 303, hunt);
    const oldHunt = assert.rejects(task, /switched off/);
    b.drain();
    await oldHunt;
    hunt = b.rpc.sethuntenabled(true);
    b.rpc.setcollectenabled(false);
    b.rpc.setheroenabled(false);
    task = b.rpc.query('return "ok"', 'hunt', 303, hunt);
    b.drain();
    assert.equal(await task, 'ok', 'Collection/recovery-off must preserve hunting');
    const collectHuntIsolation = b.rpc.setcollectenabled(true);
    b.rpc.sethuntenabled(false);
    task = b.rpc.query('return "ok"', 'collect', 303, collectHuntIsolation);
    b.drain();
    assert.equal(await task, 'ok', 'Hunt-off must preserve collection');
    b.rpc.close();
    b = bridge();
    task = b.rpc.query('return "ok"', 'league', 303, 0);
    const leagueOff = assert.rejects(task, /switched off/);
    b.drain();
    await leagueOff;
    const league = b.rpc.setleagueenabled(true);
    task = b.rpc.query('return "ok"', 'league', 303, league);
    const leagueCanceled = assert.rejects(task, /Alliance collection switch changed/);
    b.rpc.setleagueenabled(false);
    await leagueCanceled;
    b.rpc.setleagueenabled(true);
    task = b.rpc.query('return "ok"', 'league', 303, league);
    const oldLeague = assert.rejects(task, /switched off/);
    b.drain();
    await oldLeague;
    const liveLeague = b.rpc.setleagueenabled(true);
    b.rpc.setcollectenabled(false);
    b.rpc.sethuntenabled(false);
    b.rpc.setheroenabled(false);
    task = b.rpc.query('return "ok"', 'league', 303, liveLeague);
    b.drain();
    assert.equal(await task, 'ok', 'Other switches must preserve alliance collection');
    const liveCollect = b.rpc.setcollectenabled(true);
    b.rpc.setleagueenabled(false);
    task = b.rpc.query('return "ok"', 'collect', 303, liveCollect);
    b.drain();
    assert.equal(await task, 'ok', 'Alliance-off must preserve ordinary collection');
    b.rpc.close();
    b = bridge();
    b.rpc.setenabled(true, [411]);
    task = b.rpc.query('return "ok"', true, 803);
    const noScoutSelected = assert.rejects(task, /switched off/);
    b.drain();
    await noScoutSelected;
    b.rpc.setenabled(true, [803]);
    task = b.rpc.query('return "ok"', true, 803);
    b.drain();
    assert.equal(await task, 'ok', 'Selected scouts may train normally');
    task = b.rpc.query('return "ok"', 'train_speed', 803);
    const scoutItemsOff = assert.rejects(task, /switched off/);
    b.drain();
    await scoutItemsOff;
    b.rpc.setenabled(true, [803], true);
    task = b.rpc.query('return "ok"', 'train_speed', 803);
    b.drain();
    assert.equal(await task, 'ok', 'Scouts may accelerate only after explicit item opt-in');
    task = b.rpc.query('return "ok"', true, 803);
    const scoutStopped = assert.rejects(task, /switched off/);
    b.rpc.setenabled(false, []);
    await scoutStopped;
    assert.throws(() => b.rpc.setenabled(true, [414]), /Invalid troop selection/);
    b.rpc.close();
    b = bridge();
    task = b.rpc.query('return "ok"', 'beacon', 303, 0);
    const beaconOff = assert.rejects(task, /switched off/);
    b.drain();
    await beaconOff;
    const beaconEpoch = b.rpc.setbeaconenabled(true);
    task = b.rpc.query('return "ok"', 'beacon', 303, beaconEpoch);
    b.rpc.setcollectenabled(false);
    b.rpc.setleagueenabled(false);
    b.drain();
    assert.equal(await task, 'ok', 'Other feature gates cannot cancel a rescue action');
    task = b.rpc.query('return "ok"', 'beacon', 303, beaconEpoch);
    const beaconCancelled = assert.rejects(task, /switch changed/);
    b.rpc.setbeaconenabled(false);
    await beaconCancelled;
    b.rpc.setbeaconenabled(true);
    task = b.rpc.query('return "ok"', 'beacon', 303, beaconEpoch);
    const beaconStale = assert.rejects(task, /switched off/);
    b.drain();
    await beaconStale;
    b.rpc.close();
    process.stdout.write('Bridge gate tests passed (11 scenarios).\n');
}

main().catch(error => { process.stderr.write(String(error) + '\n'); process.exitCode = 1; });
