/**
 * pow_worker.c - High-performance Proof-of-Work nonce finder for Alien Worlds
 * Compile: gcc -O3 -o pow_worker pow_worker.c -lcrypto
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <openssl/sha.h>

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
    
    // Start from random position
    srand(time(NULL));
    uint64_t nonce = ((uint64_t)rand() << 32) | rand();
    
    uint8_t data[24];
    memcpy(data, prefix, 16);
    
    clock_t start_time = clock();
    uint64_t iterations = 0;
    uint8_t hash[SHA256_DIGEST_LENGTH];
    
    while (1) {
        uint64_to_le(nonce, data + 16);
        SHA256(data, 24, hash);
        iterations++;
        
        // Check difficulty: hash[0] == 0 && hash[1] == 0 && hash[2] < 16
        if (hash[0] == 0 && hash[1] == 0 && hash[2] < 16) {
            double elapsed = (double)(clock() - start_time) / CLOCKS_PER_SEC;
            uint64_t hashrate = (uint64_t)(iterations / elapsed);
            
            char nonce_hex[17];
            uint8_t nonce_buf[8];
            uint64_to_le(nonce, nonce_buf);
            bytes_to_hex(nonce_buf, 8, nonce_hex);
            
            printf("{\"success\":true,\"nonce\":\"%s\",\"iterations\":%llu,\"timeMs\":%d,\"hashrate\":%llu}\n",
                   nonce_hex, (unsigned long long)iterations, (int)(elapsed * 1000), (unsigned long long)hashrate);
            return 0;
        }
        
        nonce++;
        
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
