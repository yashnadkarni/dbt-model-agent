WITH filtered_orders AS (
    SELECT
        order_id,
        customer_id,
        order_date,
        promised_delivery_date,
        cleaned_ship_date,
        COALESCE(NULLIF(promised_delivery_date < cleaned_ship_date, FALSE), FALSE) AS is_delayed
    FROM {{ source('sales_warehouse', 'raw_orders') }}
    WHERE order_id > 0
)
SELECT *
FROM filtered_orders;
