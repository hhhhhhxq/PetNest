#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>

#include <arpa/inet.h>
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static volatile sig_atomic_t keep_running = 1;

static void stop_running(int signal_number) {
    (void)signal_number;
    keep_running = 0;
}

static int64_t system_idle_milliseconds(void) {
    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("IOHIDSystem")
    );
    if (service == IO_OBJECT_NULL) {
        return -1;
    }

    CFTypeRef value = IORegistryEntryCreateCFProperty(
        service,
        CFSTR("HIDIdleTime"),
        kCFAllocatorDefault,
        0
    );
    IOObjectRelease(service);
    if (value == NULL || CFGetTypeID(value) != CFNumberGetTypeID()) {
        if (value != NULL) {
            CFRelease(value);
        }
        return -1;
    }

    int64_t nanoseconds = 0;
    Boolean converted = CFNumberGetValue(
        (CFNumberRef)value,
        kCFNumberSInt64Type,
        &nanoseconds
    );
    CFRelease(value);
    if (!converted || nanoseconds < 0) {
        return -1;
    }
    return nanoseconds / 1000000;
}

static int process_is_alive(pid_t process_id) {
    if (kill(process_id, 0) == 0) {
        return 1;
    }
    return errno != ESRCH;
}

static void send_line(int socket_fd, const struct sockaddr_in *target, const char *line) {
    sendto(
        socket_fd,
        line,
        strlen(line),
        0,
        (const struct sockaddr *)target,
        sizeof(*target)
    );
}

int main(int argc, char **argv) {
    int event_port = 0;
    pid_t host_process_id = 0;
    for (int index = 1; index + 1 < argc; index += 2) {
        if (strcmp(argv[index], "--event-port") == 0) {
            event_port = atoi(argv[index + 1]);
        } else if (strcmp(argv[index], "--host-process-id") == 0) {
            host_process_id = (pid_t)atoi(argv[index + 1]);
        }
    }
    if (event_port < 1024 || event_port > 65535 || host_process_id <= 0) {
        fprintf(stderr, "Usage: macos-idle-bridge --event-port PORT --host-process-id PID\n");
        return 2;
    }

    signal(SIGINT, stop_running);
    signal(SIGTERM, stop_running);

    int socket_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_fd < 0) {
        return 3;
    }
    struct sockaddr_in target;
    memset(&target, 0, sizeof(target));
    target.sin_family = AF_INET;
    target.sin_port = htons((uint16_t)event_port);
    target.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    send_line(socket_fd, &target, "READY");
    while (keep_running && process_is_alive(host_process_id)) {
        int64_t idle_ms = system_idle_milliseconds();
        if (idle_ms >= 0) {
            char message[64];
            snprintf(message, sizeof(message), "IDLE\t%lld", (long long)idle_ms);
            send_line(socket_fd, &target, message);
        }
        usleep(250000);
    }
    close(socket_fd);
    return 0;
}
