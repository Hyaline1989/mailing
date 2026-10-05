<?php
declare(strict_types=1);

$baseDir = __DIR__;
$rawInput = file_get_contents('php://input') ?: '';
$receivedAt = date('c');

if ($rawInput === '') {
    http_response_code(200);
    echo 'ok';
    exit;
}

$event = json_decode($rawInput, true);
if (!is_array($event)) {
    file_put_contents(
        $baseDir . '/max_webhook_errors.log',
        '[' . $receivedAt . '] Invalid JSON: ' . $rawInput . PHP_EOL,
        FILE_APPEND | LOCK_EX
    );
    http_response_code(200);
    echo 'ok';
    exit;
}

file_put_contents(
    $baseDir . '/max_webhook_events.log',
    json_encode(
        [
            'received_at' => $receivedAt,
            'event' => $event,
        ],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
    ) . PHP_EOL,
    FILE_APPEND | LOCK_EX
);

function collectUsers(mixed $value, array &$users): void
{
    if (is_array($value)) {
        if (array_key_exists('user_id', $value)) {
            $userId = (string) $value['user_id'];
            $users[$userId] = [
                'user_id' => $userId,
                'name' => $value['name'] ?? trim(($value['first_name'] ?? '') . ' ' . ($value['last_name'] ?? '')),
                'username' => $value['username'] ?? '',
                'last_seen_at' => date('c'),
            ];
        }

        foreach ($value as $child) {
            collectUsers($child, $users);
        }
    }
}

$usersFile = $baseDir . '/max_users.json';
$users = [];
if (is_file($usersFile)) {
    $savedUsers = json_decode(file_get_contents($usersFile) ?: '{}', true);
    if (is_array($savedUsers)) {
        $users = $savedUsers;
    }
}

collectUsers($event, $users);

file_put_contents(
    $usersFile,
    json_encode($users, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT),
    LOCK_EX
);

http_response_code(200);
echo 'ok';
