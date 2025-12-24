/**
 * pow_worker.c - Optimized Proof-of-Work nonce finder for Alien Worlds
 * Features:
 *   - OpenSSL SHA256 with state caching (prefix computed once)
 *   - Batch hashing (4 nonces at a time)
 * Compile: gcc -O3 -o pow_worker pow_worker.c -lcrypto
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <openssl/sha.h>

#define BATCH_SIZE 4  // Hash 4 nonces at a time

// EOSIO name character map
static const char charmap[] = ".12345abcdefghijklmnopqrstuvwxyz";

// Convert account name to EOSIO uint64 format
uint64_t string_to_name(const char* str) {
    uint64_t value = 0;
    int len = strlen(str);
    
    for (int i = 0; i < 12 && i < len; i++) {
        uint64_t c = 0;
        char ch = str[i];
        
        if (ch >= 'a' && ch <= 'z') {
            c = (ch - 'a') + 6;
        } else if (ch >= '1' && ch <= '5') {
            c = (ch - '1') + 1;
        } else if (ch == '.') {
            c = 0;
        }
        
        value |= (c << (64 - 5 * (i + 1)));
    }
    
    if (len > 12) {
        uint64_t c = 0;
        char ch = str[12];
        
        if (ch >= 'a' && ch <= 'z') {
            c = (ch - 'a') + 6;
        } else if (ch >= '1' && ch <= '5') {
            c = (ch - '1') + 1;
        }
        
        value |= (c & 0x0F);
    }
    
    return value;
}

// Write uint64 as little-endian bytes
void uint64_to_le(uint64_t val, uint8_t* buf) {
    for (int i = 0; i < 8; i++) {
        buf[i] = (uint8_t)(val & 0xFF);
        val >>= 8;
    }
}

// Convert hex string to bytes
void hex_to_bytes(const char* hex, uint8_t* bytes, int len) {
    for (int i = 0; i < len; i++) {
        sscanf(hex + (i * 2), "%2hhx", &bytes[i]);
    }
}

// Convert bytes to hex string
void bytes_to_hex(const uint8_t* bytes, int len, char* hex) {
    for (int i = 0; i < len; i++) {
        sprintf(hex + (i * 2), "%02x", bytes[i]);
    }
    hex[len * 2] = '\0';
}

// Check if hash meets difficulty: hash[0]==0 && hash[1]==0 && hash[2]<16
static inline int check_difficulty(const uint8_t* hash) {
    return (hash[0] == 0 && hash[1] == 0 && hash[2] < 16);
}

int main() {
    char input[1024];
    char account[64];
    char last_mine_tx[128];
    
    // Read JSON input from stdin
    if (fgets(input, sizeof(input), stdin) == NULL) {
        printf("{\"success\":false,\"error\":\"No input\"}\n");
        return 1;
    }
    
    // Simple JSON parsing
    char* acc_start = strstr(input, "\"account\"");
    char* tx_start = strstr(input, "\"lastMineTx\"");
    
    if (!acc_start || !tx_start) {
        printf("{\"success\":false,\"error\":\"Invalid JSON\"}\n");
        return 1;
    }
    
    // Extract account
    acc_start = strchr(acc_start, ':');
    acc_start = strchr(acc_start, '"') + 1;
    char* acc_end = strchr(acc_start, '"');
    strncpy(account, acc_start, acc_end - acc_start);
    account[acc_end - acc_start] = '\0';
    
    // Extract lastMineTx
    tx_start = strchr(tx_start, ':');
    tx_start = strchr(tx_start, '"') + 1;
    char* tx_end = strchr(tx_start, '"');
    strncpy(last_mine_tx, tx_start, tx_end - tx_start);
    last_mine_tx[tx_end - tx_start] = '\0';
    
    // Prepare mining data
    uint64_t account_val = string_to_name(account);
    uint8_t account_buf[8];
    uint64_to_le(account_val, account_buf);
    
    uint8_t tx_buf[8];
    hex_to_bytes(last_mine_tx, tx_buf, 8);
    
    // Prepare prefix (account + tx first 8 bytes)
    uint8_t prefix[16];
    memcpy(prefix, account_buf, 8);
    memcpy(prefix + 8, tx_buf, 8);
    
    // === OPTIMIZATION 1: Pre-compute prefix hash state ===
    SHA256_CTX prefix_ctx;
    SHA256_Init(&prefix_ctx);
    SHA256_Update(&prefix_ctx, prefix, 16);
    // Now prefix_ctx holds the state after hashing prefix
    // We only need to add nonce (8 bytes) each iteration
    
    // Start from random position
    srand(time(NULL));
    uint64_t nonce = ((uint64_t)rand() << 32) | rand();
    
    clock_t start_time = clock();
    uint64_t iterations = 0;
    
    // === OPTIMIZATION 2: Batch hashing ===
    uint8_t nonce_bufs[BATCH_SIZE][8];
    uint8_t hashes[BATCH_SIZE][SHA256_DIGEST_LENGTH];
    SHA256_CTX ctxs[BATCH_SIZE];
    
    while (1) {
        // Prepare batch of nonces
        for (int i = 0; i < BATCH_SIZE; i++) {
            uint64_to_le(nonce + i, nonce_bufs[i]);
        }
        
        // Hash batch using cached prefix state
        for (int i = 0; i < BATCH_SIZE; i++) {
            ctxs[i] = prefix_ctx;  // Copy pre-computed state (fast!)
            SHA256_Update(&ctxs[i], nonce_bufs[i], 8);
            SHA256_Final(hashes[i], &ctxs[i]);
        }
        
        iterations += BATCH_SIZE;
        
        // Check batch for valid hash
        for (int i = 0; i < BATCH_SIZE; i++) {
            if (check_difficulty(hashes[i])) {
                double elapsed = (double)(clock() - start_time) / CLOCKS_PER_SEC;
                uint64_t hashrate = (elapsed > 0) ? (uint64_t)(iterations / elapsed) : 0;
                
                char nonce_hex[17];
                bytes_to_hex(nonce_bufs[i], 8, nonce_hex);
                
                printf("{\"success\":true,\"nonce\":\"%s\",\"iterations\":%llu,\"timeMs\":%d,\"hashrate\":%llu}\n",
                       nonce_hex, (unsigned long long)iterations, (int)(elapsed * 1000), (unsigned long long)hashrate);
                return 0;
            }
        }
        
        nonce += BATCH_SIZE;
        
        // Timeout check every 100000 iterations
        if (iterations % 100000 == 0) {
            double elapsed = (double)(clock() - start_time) / CLOCKS_PER_SEC;
            if (elapsed > 60.0) {
                printf("{\"success\":false,\"error\":\"Timeout after 60s\",\"iterations\":%llu}\n", 
                       (unsigned long long)iterations);
                return 1;
            }
        }
    }
    
    return 0;
}
