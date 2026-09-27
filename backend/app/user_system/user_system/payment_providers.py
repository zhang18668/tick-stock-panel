"""WeChat Pay API v3 Native and Alipay precreate QR integrations."""
from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


class PaymentConfigurationError(RuntimeError):
    pass


def _secret(value: str) -> bytes:
    if not value:
        raise PaymentConfigurationError("payment channel is not configured")
    path = Path(value)
    return path.read_bytes() if "BEGIN " not in value and path.is_file() else value.encode()


def configured_channels() -> dict[str, bool]:
    return {
        "wechat": all((settings.payment_public_base_url, settings.wechat_pay_app_id,
                       settings.wechat_pay_mch_id, settings.wechat_pay_serial_no,
                       settings.wechat_pay_private_key)),
        "alipay": all((settings.payment_public_base_url, settings.alipay_app_id,
                       settings.alipay_private_key, settings.alipay_public_key)),
    }


def _rsa_sign(private_key: str, message: str) -> str:
    key = serialization.load_pem_private_key(_secret(private_key), password=None)
    signature = key.sign(message.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()


def _rsa_verify(public_key: str, message: bytes, signature: str) -> None:
    key = serialization.load_pem_public_key(_secret(public_key))
    key.verify(base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256())


def parse_wechat_callback(body: bytes, timestamp: str, nonce: str, signature: str) -> dict:
    _rsa_verify(
        settings.wechat_pay_platform_public_key,
        f"{timestamp}\n{nonce}\n{body.decode()}\n".encode(),
        signature,
    )
    resource = json.loads(body)["resource"]
    plaintext = AESGCM(settings.wechat_pay_api_v3_key.encode()).decrypt(
        base64.b64decode(resource["nonce"]),
        base64.b64decode(resource["ciphertext"]),
        resource.get("associated_data", "").encode(),
    )
    return json.loads(plaintext)


def verify_alipay_callback(params: dict[str, str]) -> None:
    signature = params["sign"]
    content = "&".join(
        f"{key}={value}" for key, value in sorted(params.items())
        if key not in {"sign", "sign_type"} and value != ""
    )
    _rsa_verify(settings.alipay_public_key, content.encode("utf-8"), signature)


async def create_wechat_qr(out_trade_no: str, amount_cents: int, description: str) -> str:
    body = json.dumps({
        "appid": settings.wechat_pay_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "description": description,
        "out_trade_no": out_trade_no,
        "notify_url": f"{settings.payment_public_base_url.rstrip('/')}/api/billing/webhooks/wechat",
        "amount": {"total": amount_cents, "currency": "CNY"},
    }, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    path = "/v3/pay/transactions/native"
    signature = _rsa_sign(
        settings.wechat_pay_private_key,
        f"POST\n{path}\n{timestamp}\n{nonce}\n{body}\n",
    )
    authorization = (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{settings.wechat_pay_mch_id}",nonce_str="{nonce}",'
        f'signature="{signature}",timestamp="{timestamp}",'
        f'serial_no="{settings.wechat_pay_serial_no}"'
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.mch.weixin.qq.com{path}",
            content=body.encode(),
            headers={"Authorization": authorization, "Accept": "application/json",
                     "Content-Type": "application/json", "User-Agent": "ChenFengQuant/1.0"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"WeChat Pay order failed ({response.status_code})")
    code_url = response.json().get("code_url")
    if not code_url:
        raise RuntimeError("WeChat Pay response did not contain code_url")
    return str(code_url)


async def create_alipay_qr(out_trade_no: str, amount_cents: int, description: str) -> str:
    params = {
        "app_id": settings.alipay_app_id,
        "method": "alipay.trade.precreate",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": f"{settings.payment_public_base_url.rstrip('/')}/api/billing/webhooks/alipay",
        "biz_content": json.dumps({
            "out_trade_no": out_trade_no,
            "total_amount": f"{amount_cents / 100:.2f}",
            "subject": description,
            "timeout_express": "15m",
        }, ensure_ascii=False, separators=(",", ":")),
    }
    content = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["sign"] = _rsa_sign(settings.alipay_private_key, content)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post("https://openapi.alipay.com/gateway.do", data=params)
    payload = response.json().get("alipay_trade_precreate_response", {})
    if payload.get("code") != "10000" or not payload.get("qr_code"):
        raise RuntimeError(f"Alipay order failed: {payload.get('sub_msg') or payload.get('msg') or 'unknown error'}")
    return str(payload["qr_code"])


async def create_qr(provider: str, out_trade_no: str, amount_cents: int, description: str) -> str:
    if not configured_channels().get(provider):
        raise PaymentConfigurationError(f"{provider} payment is not configured")
    if provider == "wechat":
        return await create_wechat_qr(out_trade_no, amount_cents, description)
    if provider == "alipay":
        return await create_alipay_qr(out_trade_no, amount_cents, description)
    raise ValueError("unsupported payment provider")
