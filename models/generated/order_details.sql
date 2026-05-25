{{ config(materialized='table') }}

WITH orders AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_orders') }}
),

customers AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_customers') }}
)

SELECT
    orders.id AS order_id,
    orders.user_id AS customer_id,
    orders.order_date,
    orders.status,
    customers.first_name || ' ' || customers.last_name AS customer_name,
    orders.amount / 100.0 AS amount_dollars
FROM orders
LEFT JOIN customers
    ON orders.user_id = customers.id
