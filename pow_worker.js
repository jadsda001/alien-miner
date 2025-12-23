/**
 * pow_worker.js - High-performance Proof-of-Work nonce finder
 * เร็วกว่า Python hashlib ประมาณ 5-10x เพราะ Node.js crypto เป็น native C++ bindings
 */

const crypto = require('crypto');

// Helper: Convert account name to EOSIO name format (uint64)
function stringToName(s) {
    const charmap = '.12345abcdefghijklmnopqrstuvwxyz';
    let value = BigInt(0);
    for (let i = 0; i < Math.min(s.length, 12); i++) {
        let c = s.charCodeAt(i);
        let charValue;
        if (c >= 'a'.charCodeAt(0) && c <= 'z'.charCodeAt(0)) {
            charValue = BigInt((c - 'a'.charCodeAt(0)) + 6);
        } else if (c >= '1'.charCodeAt(0) && c <= '5'.charCodeAt(0)) {
            charValue = BigInt((c - '1'.charCodeAt(0)) + 1);
        } else if (c === '.'.charCodeAt(0)) {
            charValue = BigInt(0);
        } else {
            charValue = BigInt(0);
        }
        if (i < 12) {
            value = value | (charValue << BigInt(64 - 5 * (i + 1)));
        }
    }
    if (s.length > 12) {
        let c = s.charCodeAt(12);
        let charValue;
        if (c >= 'a'.charCodeAt(0) && c <= 'z'.charCodeAt(0)) {
            charValue = BigInt((c - 'a'.charCodeAt(0)) + 6);
        } else if (c >= '1'.charCodeAt(0) && c <= '5'.charCodeAt(0)) {
            charValue = BigInt((c - '1'.charCodeAt(0)) + 1);
        } else {
            charValue = BigInt(0);
        }
        value = value | (charValue & BigInt(0x0F));
    }
    return value;
}

// Write BigInt as little-endian 8 bytes
function uint64ToBuffer(val) {
    const buf = Buffer.alloc(8);
    let v = BigInt.asUintN(64, val);
    for (let i = 0; i < 8; i++) {
        buf[i] = Number(v & BigInt(0xFF));
        v = v >> BigInt(8);
    }
    return buf;
}

/**
 * Find valid nonce for Alien Worlds mining
 * Target: first 2 bytes === 0 && third byte < 16
 */
function findNonce(accountName, lastMineTxHex) {
    const accountVal = stringToName(accountName);
    const accountBuf = uint64ToBuffer(accountVal);
    const txBuf = Buffer.from(lastMineTxHex.substring(0, 16), 'hex');
    const prefix = Buffer.concat([accountBuf, txBuf]);

    // Start from random position for distribution
    let nonce = BigInt(Math.floor(Math.random() * Number.MAX_SAFE_INTEGER));
    const maxNonce = BigInt('0xFFFFFFFFFFFFFFFF');

    const startTime = Date.now();
    let iterations = 0;

    while (true) {
        const nonceBuf = uint64ToBuffer(nonce);
        const data = Buffer.concat([prefix, nonceBuf]);
        const hash = crypto.createHash('sha256').update(data).digest();

        iterations++;

        // Check difficulty: h[0] == 0 && h[1] == 0 && h[2] < 16
        if (hash[0] === 0 && hash[1] === 0 && hash[2] < 16) {
            const elapsedMs = Date.now() - startTime;
            return {
                success: true,
                nonce: nonceBuf.toString('hex'),
                iterations: iterations,
                timeMs: elapsedMs,
                hashrate: Math.round(iterations / (elapsedMs / 1000))
            };
        }

        nonce++;
        if (nonce > maxNonce) nonce = BigInt(0);

        // Safety timeout: 60 seconds max
        if (iterations % 100000 === 0) {
            if (Date.now() - startTime > 60000) {
                return {
                    success: false,
                    error: 'Timeout after 60s',
                    iterations: iterations
                };
            }
        }
    }
}

// Main: Read input from stdin
let inputData = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => inputData += chunk);
process.stdin.on('end', () => {
    try {
        const input = JSON.parse(inputData);
        const result = findNonce(input.account, input.lastMineTx);
        console.log(JSON.stringify(result));
    } catch (e) {
        console.log(JSON.stringify({ success: false, error: e.message }));
    }
});
