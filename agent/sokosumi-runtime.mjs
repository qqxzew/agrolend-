import {dirname,join,isAbsolute} from 'node:path';
import {pathToFileURL} from 'node:url';
import {runSokosumi} from './sokosumi-cli.mjs';
let loaded;
export function sokosumiRoot(run=(command,args,options)=>runSokosumi(args,options)){
 const skillsPath=run('sokosumi',['skills','path'],{encoding:'utf8',timeout:30000}).trim().replace(/[\\/]+$/u,'');
 if(!isAbsolute(skillsPath)||!/[\\/]skills$/u.test(skillsPath))throw new Error('sokosumi skills path returned an invalid package path');
 return join(dirname(skillsPath),'dist','src');
}
export async function loadSokosumiRuntime(){
 if(!loaded){const root=sokosumiRoot();
  loaded=Promise.all(['coworker/runtime-credentials.js','api/http-client.js','api/services/task-service.js'].map(p=>import(pathToFileURL(join(root,p)).href))).then(modules=>Object.assign({},...modules));
 }
 return loaded;
}
