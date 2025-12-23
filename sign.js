const { Api, JsonRpc, RpcError } = require('eosjs');
const { JsSignatureProvider } = require('eosjs/dist/eosjs-jssig');
const fetch = require('node-fetch');
const { TextEncoder, TextDecoder } = require('util');

const readInput = () => {
    return new Promise((resolve, reject) => {
        let data = '';
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', chunk => data += chunk);
        process.stdin.on('end', () => resolve(data));
        process.stdin.on('error', reject);
    });
};

(async () => {
    try {
        const inputData = await readInput();
        const payload = JSON.parse(inputData);
        
        // รองรับทั้งแบบกุญแจเดียวและหลายกุญแจ
        let keys = [];
        if (payload.privateKeys) {
            keys = payload.privateKeys;
        } else if (payload.privateKey) {
            keys = [payload.privateKey];
        }

        const signatureProvider = new JsSignatureProvider(keys);
        const rpc = new JsonRpc(payload.rpcUrl, { fetch });
        const api = new Api({ rpc, signatureProvider, textDecoder: new TextDecoder(), textEncoder: new TextEncoder() });

        const result = await api.transact({
            actions: payload.actions
        }, {
            blocksBehind: 3,
            expireSeconds: 30,
        });

        console.log(JSON.stringify({ 
            success: true, 
            transaction_id: result.transaction_id,
            traces: result.processed ? result.processed.action_traces : [] 
        }));

    } catch (e) {
        let errorMessage = e.message;
        if (e instanceof RpcError) {
            try {
                errorMessage = e.json.error.details[0].message;
            } catch (err) {
                errorMessage = JSON.stringify(e.json, null, 2);
            }
        }
        console.log(JSON.stringify({ success: false, error: errorMessage }));
    }
})();