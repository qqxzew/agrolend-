import {test} from 'node:test';
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {eveAddress,eveArgs,eveBinary} from './start.mjs';
import {sokosumiRoot} from './sokosumi-runtime.mjs';
test('Eve rejects a mismatched port or exposed listener',()=>{
 assert.throws(()=>eveAddress({EVE_PORT:'21949',EVE_URL:'http://127.0.0.1:21950'}),/must match/);
 assert.throws(()=>eveAddress({EVE_URL:'http://0.0.0.0:21949'}),/must match/);
 assert.throws(()=>eveAddress({EVE_PORT:'0'}),/integer/);
 assert.deepEqual(eveAddress({EVE_URL:'http://127.0.0.1:21949'}),{port:21949,url:'http://127.0.0.1:21949'});
});
test('Eve runs the compiled agent only when asked, always on loopback',()=>{
 assert.deepEqual(eveArgs({},21949).slice(0,1),['dev']);
 assert.deepEqual(eveArgs({EVE_MODE:'start'},21949),['start','--host','127.0.0.1','--port','21949']);
 assert.throws(()=>eveArgs({EVE_MODE:'prod'},21949),/dev or start/);
});
test('Eve executable resolves through Node package lookup',()=>{
 assert.match(eveBinary(),/node_modules[\\/]eve[\\/]bin[\\/]eve\.js$/);
});
test('runtime root derives from supported installed CLI output',()=>{
 assert.equal(sokosumiRoot((command,args)=>{assert.equal(command,'sokosumi');assert.deepEqual(args,['skills','path']);return '/opt/node/lib/node_modules/@masumi_network/sokosumi/skills\n';}),join('/opt/node/lib/node_modules/@masumi_network/sokosumi','dist','src'));
 assert.equal(sokosumiRoot(()=>'C:\\Users\\x\\npm\\node_modules\\@masumi_network\\sokosumi\\skills\\\n'),join('C:\\Users\\x\\npm\\node_modules\\@masumi_network\\sokosumi','dist','src'));
 assert.throws(()=>sokosumiRoot(()=>'/unrelated'),/invalid package path/);
});
