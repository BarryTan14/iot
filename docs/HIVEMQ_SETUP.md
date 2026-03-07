# HiveMQ Cloud setup for Evicted SMS queue

This guide connects the Evicted service to **HiveMQ Cloud** so SMS events are published to a hosted MQTT broker. A separate subscriber can then consume messages and call your SMS API.

## 1. Create a HiveMQ Cloud cluster

1. Go to [HiveMQ Cloud](https://www.hivemq.com/mqtt-cloud-broker/) and sign up or log in.
2. Create a **new cluster** (e.g. free tier / Starter trial). Wait until it shows **Running**.
3. Open the cluster: click **Manage Cluster** for your cluster.
4. On the cluster page, note the **Connection details** (URL, Port **8883**). The host is the broker host (e.g. `xxxxxxxxxxxx.s1.eu.hivemq.cloud`).

## 2. Create Access Credentials (username + password)

HiveMQ Cloud uses **Access Credentials**, not a separate “Users” page. Create them like this:

1. With your cluster open, go to the **Access Management** tab (not Connect).
2. In the **Authentication** section, find **Access Credentials** (or **Credentials**).
3. Click **Edit** in that Credentials area so the form expands.
4. Click **Add Credentials** (or **Create Credential**).
5. Enter a **Username** and **Password** (e.g. `evicted-app` and a strong password). For **Role**, choose the default (e.g. **Allow All**) so the client can publish.
6. Click **Save**.

Use this username and password as `MQTT_USERNAME` and `MQTT_PASSWORD` in the Evicted app.

If you don’t see **Access Credentials** or **Edit**:
- Make sure you’re in **Access Management**, not Overview or Connect.
- On **Serverless** plans the control may say **Create Credential** and ask for Username, Password, and **Permission** (choose “Publish and subscribe” or “Publish only” for the Evicted app).

## 3. Configure the Evicted service

Set these environment variables (e.g. in `.env` or your host’s env). Replace with your HiveMQ Cloud values:

```env
# HiveMQ Cloud broker (from cluster Connect / Access Management)
MQTT_BROKER_HOST=xxxxxxxxxxxx.s1.eu.hivemq.cloud
MQTT_BROKER_PORT=8883
MQTT_USE_TLS=1

# Credentials (from Access Credentials in HiveMQ Cloud)
MQTT_USERNAME=your_username
MQTT_PASSWORD=your_password

# Optional: topic and client id (defaults are fine)
# MQTT_TOPIC_SMS=evicted/sms/send
# MQTT_CLIENT_ID=evicted-frontend
```

- **MQTT_BROKER_HOST**: Your cluster hostname from HiveMQ Cloud.
- **MQTT_BROKER_PORT**: Use **8883** for TLS (required by HiveMQ Cloud).
- **MQTT_USE_TLS**: Set to `1` (or `true`/`yes`) to enable TLS.
- **MQTT_USERNAME** / **MQTT_PASSWORD**: The Access Credentials you created in step 2.

Restart the Evicted app after changing env vars.

## 4. Verify the connection

1. Start the Evicted app.
2. Publish an SMS event:

```bash
curl -X POST http://localhost:8000/api/queue-sms/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+15551234567", "message": "Test from Evicted"}'
```

3. In HiveMQ Cloud, open **Web UI** (or **Monitoring** → **Topics**) and check that messages appear on topic `evicted/sms/send`.

## 5. Subscriber (SMS sender)

Your SMS-sending service should:

1. Connect to the **same** HiveMQ Cloud broker (same host, port 8883, TLS, same user or another user with subscribe rights).
2. Subscribe to topic: `evicted/sms/send` (or your `MQTT_TOPIC_SMS` value).
3. On each message, parse the JSON payload and call your SMS API:

```json
{"phone_number": "+15551234567", "message": "Your car is ready."}
```

Optional: use HiveMQ Cloud’s **Shared Subscriptions** if you run multiple subscriber instances for load balancing.
