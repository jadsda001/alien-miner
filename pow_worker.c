/**
 * pow_worker.c - High-performance Proof-of-Work nonce finder for Alien Worlds
 * Compile: gcc -O3 -o pow_worker pow_worker.c -lssl -lcrypto
 * 
 * Input (JSON via stdin):  {"account": "accountname", "lastMineTx": "hex..."}
 * Output (JSON via stdout): {"success": true, "nonce": "hex...", "iterations": N, "hashrate": N}
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <openssl/sha.h>

// EOSIO name character map
static const char* CHARMAP = ".12345abcdefghijklmnopqrstuvwxyz";

// Convert EOSIO account name to uint64
uint64_t string_to_name(const char* str) {
    uint64_t value = 0;
    size_t len = strlen(str);
    
    for (size_t i = 0; i < 12 && i < len; i++) {
        char c = str[i];
        uint64_t char_value = 0;
        
        if (c >= 'a' && c <= 'z') {
            char_value = (c - 'a') + 6;
        } else if (c >= '1' && c <= '5') {
            char_value = (c - '1') + 1;
        } else if (c == '.') {
            char_value = 0;
        }
        
        value |= (char_value << (64 - 5 * (i + 1)));
    }
    
    // Handle 13th character (only 4 bits)
    if (len > 12) {
        char c = str[12];
        uint64_t char_value = 0;
        
        if (c >= 'a' && c <= 'z') {
            char_value = (c - 'a') + 6;
        } else if (c >= '1' && c <= '5') {
            char_value = (c - '1') + 1;
        }
        
        value |= (char_value & 0x0F);
    }
    
    return value;
}

// Write uint64 as little-endian bytes
void uint64_to_le_bytes(uint64_t val, uint8_t* buf) {
    for (int i = 0; i < 8; i++) {
        buf[i] = (uint8_t)(val & 0xFF);
        val >>= 8;
    }
}

// Parse hex string to bytes (first 8 bytes only)
void hex_to_bytes(const char* hex, uint8_t* bytes, size_t len) {
    for (size_t i = 0; i < len && hex[i*2] && hex[i*2+1]; i++) {
        char byte_str[3] = {hex[i*2], hex[i*2+1], 0};
        bytes[i] = (uint8_t)strtol(byte_str, NULL, 16);
    }
}

// Bytes to hex string
void bytes_to_hex(const uint8_t* bytes, size_t len, char* hex) {
    for (size_t i = 0; i < len; i++) {
        sprintf(hex + i*2, "%02x", bytes[i]);
    }
    hex[len*2] = '\0';
}

// Simple JSON string extraction
char* json_get_string(const char* json, const char* key) {
    static char value[256];
    char search[64];
    snprintf(search, sizeof(search), "\"%s\":", key);
    
    const char* pos = strstr(json, search);
    if (!pos) return NULL;
    
    pos += strlen(search);
    while (*pos == ' ' || *pos == '\t') pos++;
    
    if (*pos != '"') return NULL;
    pos++;
    
    size_t i = 0;
    while (*pos && *pos != '"' && i < sizeof(value) - 1) {
        value[i++] = *pos++;
    }
    value[i] = '\0';
    
    return value;
}

int main() {
    // Read JSON input from stdin
    char input[4096];
    size_t total = 0;
    
    while (fgets(input + total, sizeof(input) - total, stdin)) {
        total += strlen(input + total);
    }
    
    // Parse input
    char* account = json_get_string(input, "account");
    char* last_mine_tx = json_get_string(input, "lastMineTx");
    
    if (!account || !last_mine_tx) {
        printf("{\"success\": false, \"error\": \"Invalid input\"}\n");
        return 1;
    }
    
    // Build prefix: account (8 bytes LE) + first 8 bytes of tx hash
    uint8_t prefix[16];
    uint64_t account_val = string_to_name(account);
    uint64_to_le_bytes(account_val, prefix);
    hex_to_bytes(last_mine_tx, prefix + 8, 8);
    
    // Random starting nonce
    srand((unsigned int)time(NULL) ^ (unsigned int)clock());
    uint64_t nonce = ((uint64_t)rand() << 32) | rand();
    
    uint8_t data[24];  // prefix (16) + nonce (8)
    memcpy(data, prefix, 16);
    
    uint8_t hash[SHA256_DIGEST_LENGTH];
    
    clock_t start_time = clock();
    uint64_t iterations = 0;
    
    while (1) {
        uint64_to_le_bytes(nonce, data + 16);
        
        SHA256(data, 24, hash);
        iterations++;
        
        // Check difficulty: hash[0] == 0 && hash[1] == 0 && hash[2] < 16
        if (hash[0] == 0 && hash[1] == 0 && hash[2] < 16) {
            clock_t end_time = clock();
            double elapsed_sec = (double)(end_time - start_time) / CLOCKS_PER_SEC;
            if (elapsed_sec < 0.001) elapsed_sec = 0.001;
            
            uint64_t hashrate = (uint64_t)(iterations / elapsed_sec);
            
            char nonce_hex[17];
            uint8_t nonce_bytes[8];
            uint64_to_le_bytes(nonce, nonce_bytes);
            bytes_to_hex(nonce_bytes, 8, nonce_hex);
            
            printf("{\"success\": true, \"nonce\": \"%s\", \"iterations\": %llu, \"timeMs\": %llu, \"hashrate\": %llu}\n",
                   nonce_hex,
                   (unsigned long long)iterations,
                   (unsigned long long)(elapsed_sec * 1000),
                   (unsigned long long)hashrate);
            
            return 0;
        }
        
        nonce++;
        
        // Timeout check every 100k iterations (60 seconds max)
        if (iterations % 100000 == 0) {
            clock_t now = clock();
            double elapsed = (double)(now - start_time) / CLOCKS_PER_SEC;
            if (elapsed > 60.0) {
                printf("{\"success\": false, \"error\": \"Timeout after 60s\", \"iterations\": %llu}\n",
                       (unsigned long long)iterations);
                return 1;
            }
        }
    }
    
    return 0;
}
