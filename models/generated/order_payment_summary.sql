{{ config(materialized='table') }}

with orders as (
    select
        id as order_id,
        user_id,
        status as order_status
    from {{ source('jaffle_shop', 'raw_orders') }}
),
payments as (
    select
        order_id,
        UPPER(payment_method) as payment_method,
        amount / 100.0 as payment_amount
    from {{ source('jaffle_shop', 'raw_payments') }}
)

select
    o.order_id,
    o.user_id,
    o.order_status,
    sum(p.payment_amount) as total_paid,
    count(p.payment_amount) as num_payments
from orders o
inner join payments p on o.order_id = p.order_id
group by
    o.order_id,
    o.user_id,
    o.order_status
