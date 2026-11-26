// Offline SDK cipher only: never call login, save, update, or SDK account selection.
// Bundled with frida.Compiler so the Java bridge is inlined; see account_rekey_agent.bundle.js.
import Java from 'frida-java-bridge';

rpc.exports = {
  // Transform credential columns in memory and verify encryption by decrypting it again.
  transform(mode, values) {
    return new Promise(resolve => Java.perform(() => {
      try {
        if (!['decode', 'encode'].includes(mode)) throw new Error();
        // QQ stores a pay token in place of the WeChat refresh token; take only these named columns.
        const allowed = ['access_token', 'refresh_token', 'pay_token', 'pf', 'pf_key'];
        const fields = Object.keys(values || {});
        if (!fields.length || fields.some(field => !allowed.includes(field))) throw new Error();
        const cipher = Java.use('com.tencent.msdk.a.e').$new(
          Java.use('com.tencent.msdk.db.WxLoginModel').$new().gk());
        const Base64 = Java.use('android.util.Base64');
        const result = {};
        for (const field of fields) {
          if (mode === 'decode') {
            const bytes = cipher.f2(values[field]);
            if (!bytes || bytes.length === 0) throw new Error();
            result[field] = String(Base64.encodeToString(bytes, 2));
          } else {
            const bytes = Base64.decode(values[field], 2);
            if (!bytes || bytes.length === 0) throw new Error();
            result[field] = String(cipher.f3(bytes));
            if (String(Base64.encodeToString(cipher.f2(result[field]), 2)) !== values[field])
              throw new Error();
          }
        }
        resolve({ok: true, values: result});
      } catch (_) {
        resolve({ok: false}); // Native exceptions may contain credentials; never return them.
      }
    }));
  }
};
