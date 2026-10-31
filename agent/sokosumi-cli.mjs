import {execFileSync} from 'node:child_process';
import {join} from 'node:path';
let windowsEntry;
// On Windows the global `sokosumi` is a .cmd shim that execFileSync cannot start; run the CLI's JS entry with this Node instead.
export function sokosumiCommand(args,{platform=process.platform,env=process.env,run=execFileSync}={}){
 if(platform!=='win32')return {file:'sokosumi',args};
 windowsEntry??=env.SOKOSUMI_CLI_JS||join(run('npm',['root','-g'],{encoding:'utf8',shell:true}).trim(),'@masumi_network','sokosumi','dist','bin','sokosumi.js');
 return {file:process.execPath,args:[windowsEntry,...args]};
}
export function runSokosumi(args,options){
 const command=sokosumiCommand(args);
 return execFileSync(command.file,command.args,options);
}
