WITH fencing AS ({{protection_read_fence}}), events AS ({{protection_read}})
SELECT f.live_attempt AS live_attempt, f.lock_owned AS lock_owned,
 EXISTS ({{protection_activation}}) AS protection_active, e.*
FROM fencing f LEFT JOIN events e ON f.live_attempt AND f.lock_owned
ORDER BY e.EVENT_ID
