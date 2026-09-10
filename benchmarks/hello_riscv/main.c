#include <stdint.h>
#include <stdio.h>

int main(void)
{
    volatile int32_t sum = 0;

    for (int32_t i = 0; i < 1000; ++i) {
        sum += i;
    }

    printf("RESULT sum=%d\n", sum);

    return sum == 499500 ? 0 : 1;
}