import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sokosumiCommand} from './sokosumi-cli.mjs';
test('CLI is launched by name on POSIX and through Node on Windows',()=>{
 assert.deepEqual(sokosumiCommand(['auth','status'],{platform:'linux'}),{file:'sokosumi',args:['auth','status']});
 const windows=sokosumiCommand(['auth','status'],{platform:'win32',env:{SOKOSUMI_CLI_JS:'C:\\cli\\sokosumi.js'}});
 assert.equal(windows.file,process.execPath);
 assert.ok(windows.args.includes('C:\\cli\\sokosumi.js')||windows.args[0].endsWith('sokosumi.js'));
 assert.deepEqual(windows.args.slice(-2),['auth','status']);
});
