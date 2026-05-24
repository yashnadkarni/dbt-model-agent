WITH orders AS (
    SELECT
        id AS order_id,
        user_id AS customer_id,
        order_date,
        status,
        amount / 100.0 AS amount_dollars
    FROM {{ source('jaffle_shop', 'raw_orders') }}
),

customers AS (
    SELECT
        id,
        first_name,
        last_name
    FROM {{ source('jaffle_shop', 'raw_customers') }}
)

SELECT
    o.order_id,
    o.customer_id,
    CONCAT(c.first_name, ' ', c.last_name) AS customer_name,
    o.order_date,
    o.status,
    o.amount_dollars
FROM orders o
LEFT JOIN customers c ON o.customer_id = c.id
