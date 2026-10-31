import {readFileSync} from 'node:fs';
// The Coworker key normally lives in the OS credential vault. A headless server has none, so the operator can instead name a
// root-only file (chmod 600, outside the repository) in SOKOSUMI_RUNTIME_KEY_FILE; the CLI then receives the key on stdin.
export function runtimeKeyFile(env=process.env){return env.SOKOSUMI_RUNTIME_KEY_FILE?.trim()||null;}
export function readRuntimeKey(coworkerId,runtime,{env=process.env,read=readFileSync}={}){
 const file=runtimeKeyFile(env);
 if(!file)return runtime.readRuntimeCredential(coworkerId);
 return runtime.parseRuntimeKeyInput(read(file,'utf8'),coworkerId);
}
// CLI options for a `runtime` command: with a key file the key goes to --api-key-stdin, never into argv.
export function runtimeCliOptions(args,key,env=process.env){
 if(!runtimeKeyFile(env)||args[0]!=='runtime')return {args,input:undefined};
 return {args:[...args,'--api-key-stdin'],input:key};
}
