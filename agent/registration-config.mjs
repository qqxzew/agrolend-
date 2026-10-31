import fs from 'node:fs';
import { parseEnv } from 'node:util';
export function requireAgentAuthor(author) {
 if (typeof author !== 'string' || !author.trim()) throw Error('AGENT_AUTHOR must contain your author name');
 return author.trim();
}
export function registrationUrl(port = '21950') {
 if (!/^\d+$/.test(String(port)) || Number(port) < 1 || Number(port) > 65535) throw Error('AGENT_API_PORT must be an integer between 1 and 65535');
 return `http://127.0.0.1:${Number(port)}`;
}
export function requireSavedRuntimeToken(path) {
 let token;
 try { token = parseEnv(fs.readFileSync(path, 'utf8')).MPS_RUNTIME_TOKEN; } catch { throw Error('Runtime key recovery required: private token file is missing or unreadable'); }
 if (!token || token.startsWith('*****')) throw Error('Runtime key recovery required: private token is missing or masked');
 return token;
}
// Payment-service 0.29 (Web3CardanoV2): pricing lives inside supportedPaymentSources[], with `fixed: [{asset, amount}]` (the API rejects `decimals` for Cardano).
// Verified against the service's own OpenAPI (GET /api-docs); the legacy top-level `AgentPricing`/`Pricing` shape is forbidden for V2.
export function v2FixedPricing(token, amount) {
 if (!token?.unit || !/^[0-9]+$/u.test(String(amount)) || BigInt(amount) <= 0n) throw Error('A positive integer base-unit amount and a token unit are required');
 return { pricingType: 'Fixed', fixed: [{ asset: token.unit, amount: String(amount) }] };
}
