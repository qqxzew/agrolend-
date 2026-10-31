import { eveChannel } from 'eve/channels/eve';
import { type AuthFn, localDev, verifyHttpBasic } from 'eve/channels/auth';
// `eve dev` admits loopback callers through localDev(). A compiled agent (`eve start`, used on the server) admits only the
// worker, which sends EVE_CLIENT_PASSWORD as HTTP Basic. The password is read per request, so it is never compiled in.
// Eve itself listens on 127.0.0.1 only.
const worker: AuthFn<Request> = (request) => {
  const password = process.env.EVE_CLIENT_PASSWORD?.trim();
  if (!password) return null;
  const result = verifyHttpBasic(request.headers.get('authorization'), { username: 'agroland-worker', password });
  return result.ok ? result.sessionAuth : null;
};
export default eveChannel({ auth: [worker, localDev()] });
