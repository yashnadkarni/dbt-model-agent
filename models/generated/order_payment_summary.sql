{{ config(materialized='table') }}

WITH orders AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_orders') }}
),

payments AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_payments') }}
)
,

transformed AS (
    SELECT
        orders.id AS order_id,
        orders.user_id,
        orders.status AS order_status,
        UPPER(payments.payment_method) AS payment_method,
        payments.amount / 100.0 AS payment_amount
    FROM orders
    INNER JOIN payments
        ON orders.id = payments.order_id
)

SELECT
    order_id,
    user_id,
    order_status,
    SUM(payment_amount) AS total_paid,
    COUNT(payment_amount) AS num_payments
FROM transformed
GROUP BY order_id, user_id, order_status
