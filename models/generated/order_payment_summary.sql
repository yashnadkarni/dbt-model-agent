WITH orders AS (
    SELECT
        id AS order_id,
        user_id,
        status AS order_status
    FROM {{ source('jaffle_shop', 'raw_orders') }}
),

payments AS (
    SELECT
        order_id,
        UPPER(payment_method) AS payment_method,
        amount / 100.0 AS payment_amount
    FROM {{ source('jaffle_shop', 'raw_payments') }}
)

SELECT
    o.order_id,
    o.user_id,
    o.order_status,
    SUM(p.payment_amount) AS total_paid,
    COUNT(p.payment_amount) AS num_payments
FROM orders AS o
INNER JOIN payments AS p ON o.order_id = p.order_id
GROUP BY
    o.order_id,
    o.user_id,
    o.order_status
;
