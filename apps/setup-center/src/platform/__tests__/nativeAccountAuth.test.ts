import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NativeAuth } from '@openkitsune/native-auth';
import { parseNativeAuthorizationResult, readNativeAccountStatus, recoverNativeAccountLogin, runNativeAccountLogin } from '../nativeAccountAuth';

const connection = vi.hoisted(() => ({base:'https://instance.example',token:'original-server-token'}));
const safeFetch = vi.hoisted(() => vi.fn());
vi.mock('../auth', () => ({ getAccessToken: () => connection.token }));
vi.mock('../servers', () => ({ getActiveServer: () => ({url:connection.base}) }));

vi.mock('@openkitsune/native-auth', () => ({ NativeAuth: {
  getRedirectUri: vi.fn(), authorize: vi.fn(), cancel: vi.fn(),
  getPendingResult: vi.fn(), clearPendingResult: vi.fn(),
} }));
const base = 'https://instance.example';
const redirect = 'https://account.openkitsune.cn/oauth/mobile/callback';
const state = 'random-state';
const url = `${redirect}?state=${state}&code=one-time-code`;
const result = { state, url };
const response = (data: unknown) => new Response(JSON.stringify(data));
const start = () => response({flow:'native',attempt_id:'attempt',expires_in:180,
  authorization_url:`https://account.openkitsune.cn/oauth/authorize?redirect_uri=${encodeURIComponent(redirect)}&state=${state}&code_challenge=challenge&code_challenge_method=S256`});

describe('native account authorization delivery', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear();
    vi.stubGlobal('fetch',safeFetch);
    connection.base=base; connection.token='original-server-token';
    vi.mocked(NativeAuth.getRedirectUri).mockResolvedValue({uri:redirect});
    vi.mocked(NativeAuth.getPendingResult).mockResolvedValue({});
    vi.mocked(NativeAuth.authorize).mockResolvedValue(result);
    vi.mocked(NativeAuth.cancel).mockResolvedValue();
  });
  afterEach(() => vi.useRealTimers());

  it('opens system auth and delivers only code/state to the original instance', async () => {
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockResolvedValueOnce(response({status:'complete'}));
    await runNativeAccountLogin(base);
    expect(JSON.parse(vi.mocked(safeFetch).mock.calls[0][1]!.body as string)).toEqual({flow:'native',redirect_uri:redirect});
    expect(NativeAuth.authorize).toHaveBeenCalledWith(expect.objectContaining({state,redirectUri:redirect}));
    expect(safeFetch).toHaveBeenNthCalledWith(2,`${base}/api/account/login/native/callback/attempt`,expect.objectContaining({body:JSON.stringify({state,code:'one-time-code',error:''})}));
    expect(localStorage.length).toBe(0);
  });

  it.each([
    'https://evil.example/oauth/mobile/callback?state=random-state&code=x',
    redirect+'?state=wrong&code=x', redirect+'?state=random-state&state=random-state&code=x',
    redirect+'?state=random-state&code=x&code=y', redirect+'?state=random-state&code=x&error=denied',
    redirect+'?state=random-state', redirect+'?state=random-state&code=x#fragment',
  ])('rejects invalid callback %s', invalid => {
    expect(()=>parseNativeAuthorizationResult({base,id:'a',state,redirect,expiresAt:Date.now()+10000},{url:invalid})).toThrow('account_native_invalid_response');
  });

  it('cancels the pending backend attempt when the user closes system auth', async () => {
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockResolvedValueOnce(response({status:'cancelled'}));
    vi.mocked(NativeAuth.authorize).mockResolvedValue({state,error:'account_login_cancelled'});
    await expect(runNativeAccountLogin(base)).rejects.toThrow('account_login_cancelled');
    expect(safeFetch).toHaveBeenLastCalledWith(`${base}/api/account/login/cancel/attempt`,expect.objectContaining({method:'POST'}));
    expect(localStorage.length).toBe(0);
  });

  it('does not forward a callback after switching away from the initiating server', async () => {
    const abort = new AbortController();
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockResolvedValueOnce(response({status:'cancelled'}));
    vi.mocked(NativeAuth.authorize).mockImplementation(async () => { abort.abort(); return result; });
    await expect(runNativeAccountLogin(base,abort.signal)).rejects.toThrow('account_login_cancelled');
    expect(NativeAuth.cancel).toHaveBeenCalledOnce();
    expect(vi.mocked(safeFetch).mock.calls.some(([url])=>url.includes('/native/callback/'))).toBe(false);
  });

  it('retains routing metadata after a lost response and retries the same attempt without reopening', async () => {
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockRejectedValueOnce(new Error('network'));
    await expect(runNativeAccountLogin(base)).rejects.toThrow('network');
    const stored=localStorage.getItem('openkitsune.native-account-attempt')!;
    expect(stored).not.toContain('one-time-code');
    expect(stored).not.toContain('verifier');
    vi.mocked(NativeAuth.getPendingResult).mockResolvedValue(result);
    expect(await recoverNativeAccountLogin('https://another.example')).toBe(false);
    vi.mocked(safeFetch).mockResolvedValueOnce(response({status:'complete'}));
    await runNativeAccountLogin(base);
    expect(NativeAuth.authorize).toHaveBeenCalledOnce();
    expect(localStorage.length).toBe(0);
  });

  it('clears terminal denials so a later sign-in can start again', async () => {
    vi.mocked(NativeAuth.authorize).mockResolvedValue({state,url:redirect+'?state='+state+'&error=access_denied'});
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockResolvedValueOnce(response({status:'failed',error:'account_authorization_denied'}));
    await expect(runNativeAccountLogin(base)).rejects.toThrow('account_authorization_denied');
    expect(localStorage.length).toBe(0);
  });

  it('allows a new login when a backend restart has discarded the original attempt', async () => {
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockResolvedValueOnce(new Response('{}',{status:400}));
    await expect(runNativeAccountLogin(base)).rejects.toThrow('account_login_expired');
    expect(localStorage.length).toBe(0);
    vi.mocked(safeFetch).mockResolvedValueOnce(start()).mockResolvedValueOnce(response({status:'complete'}));
    await runNativeAccountLogin(base);
    expect(NativeAuth.authorize).toHaveBeenCalledTimes(2);
  });

  it('uses the original token to cancel even if selection changes before React cleanup runs', async () => {
    safeFetch.mockResolvedValueOnce(start()).mockResolvedValueOnce(response({status:'cancelled'}));
    vi.mocked(NativeAuth.authorize).mockImplementation(async () => {
      connection.base='https://new-server.example'; connection.token='new-server-token';
      return result;
    });
    await expect(runNativeAccountLogin(base)).rejects.toThrow('account_login_cancelled');
    expect(safeFetch.mock.calls.some(([url])=>url.includes('/native/callback/'))).toBe(false);
    const [target, options] = safeFetch.mock.calls.at(-1)!;
    expect(target).toBe(base+'/api/account/login/cancel/attempt');
    expect(options.headers.get('Authorization')).toBe('Bearer original-server-token');
  });

  it('does not publish a status fetched for a server that is no longer selected', async () => {
    safeFetch.mockImplementationOnce(async () => {
      connection.base='https://new-server.example';
      return response({status:'active'});
    });
    await expect(readNativeAccountStatus(base)).rejects.toThrow('account_login_cancelled');
  });
});
