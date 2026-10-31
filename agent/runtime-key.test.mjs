import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readRuntimeKey,runtimeCliOptions,runtimeKeyFile} from './runtime-key.mjs';
const runtime={readRuntimeCredential:id=>`vault:${id}`,parseRuntimeKeyInput:(text,id)=>`file:${id}:${text.trim()}`};
test('without a key file the OS vault is used',()=>{
 assert.equal(runtimeKeyFile({}),null);
 assert.equal(readRuntimeKey('cw',runtime,{env:{},read:()=>assert.fail('no file read')}),'vault:cw');
});
test('a key file is read and validated through the CLI parser',()=>{
 const env={SOKOSUMI_RUNTIME_KEY_FILE:' /run/key '};
 assert.equal(readRuntimeKey('cw',runtime,{env,read:path=>{assert.equal(path,'/run/key');return 'coworker_x\n';}}),'file:cw:coworker_x');
});
test('runtime commands get the key on stdin only in key-file mode',()=>{
 const env={SOKOSUMI_RUNTIME_KEY_FILE:'/run/key'};
 assert.deepEqual(runtimeCliOptions(['runtime','start','t1'],'k',env),{args:['runtime','start','t1','--api-key-stdin'],input:'k'});
 assert.deepEqual(runtimeCliOptions(['tasks','list'],'k',env),{args:['tasks','list'],input:undefined});
 assert.deepEqual(runtimeCliOptions(['runtime','start','t1'],'k',{}),{args:['runtime','start','t1'],input:undefined});
});
