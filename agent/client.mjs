import { Client } from 'eve/client';
import { writeFileSync } from 'node:fs';
// A compiled agent (server) requires the worker's HTTP Basic credential; `eve dev` admits loopback callers without it.
const password=process.env.EVE_CLIENT_PASSWORD?.trim();
export const client=new Client({host:process.env.EVE_URL,...(password?{auth:{basic:{username:'agroland-worker',password}},redirect:'error'}:{})});
export async function answer(input,journal,deadline) {
 if(typeof input!=='string'||!input.trim()||input.length>16000) throw new Error('Input must contain 1 to 16000 characters');
 const {session}=await client.sessions.create();
 writeFileSync(journal,JSON.stringify({sessionId:session.state.sessionId,phase:'sending'}),{mode:0o600});
 if(deadline!==undefined&&Date.now()>=deadline)throw new Error('Result deadline expired before model send');
 const result=await (await session.send(input)).result();
 if(result.status==='failed'||result.inputRequests.length||!result.message?.trim()) throw new Error('Turn did not return a final answer');
 writeFileSync(journal,JSON.stringify({sessionId:session.state.sessionId,phase:'answered',result:result.message}),{mode:0o600});
 return result.message;
}
