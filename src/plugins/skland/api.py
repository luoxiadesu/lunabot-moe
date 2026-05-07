"""
Skland API client for Endfield sign-in.
"""

import asyncio
import base64
import gzip
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import httpx
from Crypto.Cipher import AES, DES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad


logger = logging.getLogger("skland_api")


USER_AGENT = "Mozilla/5.0 (Linux; Android 12; SM-A5560 Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Safari/537.36; SKLand/1.52.1"

DES_RULE = {
    "appId": {"cipher": "DES", "is_encrypt": 1, "key": "uy7mzc4h", "obfuscated_name": "xx"},
    "box": {"is_encrypt": 0, "obfuscated_name": "jf"},
    "canvas": {"cipher": "DES", "is_encrypt": 1, "key": "snrn887t", "obfuscated_name": "yk"},
    "clientSize": {"cipher": "DES", "is_encrypt": 1, "key": "cpmjjgsu", "obfuscated_name": "zx"},
    "organization": {"cipher": "DES", "is_encrypt": 1, "key": "78moqjfc", "obfuscated_name": "dp"},
    "os": {"cipher": "DES", "is_encrypt": 1, "key": "je6vk6t4", "obfuscated_name": "pj"},
    "platform": {"cipher": "DES", "is_encrypt": 1, "key": "pakxhcd2", "obfuscated_name": "gm"},
    "plugins": {"cipher": "DES", "is_encrypt": 1, "key": "v51m3pzl", "obfuscated_name": "kq"},
    "pmf": {"cipher": "DES", "is_encrypt": 1, "key": "2mdeslu3", "obfuscated_name": "vw"},
    "protocol": {"is_encrypt": 0, "obfuscated_name": "protocol"},
    "referer": {"cipher": "DES", "is_encrypt": 1, "key": "y7bmrjlc", "obfuscated_name": "ab"},
    "res": {"cipher": "DES", "is_encrypt": 1, "key": "whxqm2a7", "obfuscated_name": "hf"},
    "rtype": {"cipher": "DES", "is_encrypt": 1, "key": "x8o2h2bl", "obfuscated_name": "lo"},
    "sdkver": {"cipher": "DES", "is_encrypt": 1, "key": "9q3dcxp2", "obfuscated_name": "sc"},
    "status": {"cipher": "DES", "is_encrypt": 1, "key": "2jbrxxw4", "obfuscated_name": "an"},
    "subVersion": {"cipher": "DES", "is_encrypt": 1, "key": "eo3i2puh", "obfuscated_name": "ns"},
    "svm": {"cipher": "DES", "is_encrypt": 1, "key": "fzj3kaeh", "obfuscated_name": "qr"},
    "time": {"cipher": "DES", "is_encrypt": 1, "key": "q2t3odsk", "obfuscated_name": "nb"},
    "timezone": {"cipher": "DES", "is_encrypt": 1, "key": "1uv05lj5", "obfuscated_name": "as"},
    "tn": {"cipher": "DES", "is_encrypt": 1, "key": "x9nzj1bp", "obfuscated_name": "py"},
    "trees": {"cipher": "DES", "is_encrypt": 1, "key": "acfs0xo4", "obfuscated_name": "pi"},
    "ua": {"cipher": "DES", "is_encrypt": 1, "key": "k92crp1t", "obfuscated_name": "bj"},
    "url": {"cipher": "DES", "is_encrypt": 1, "key": "y95hjkoo", "obfuscated_name": "cf"},
    "version": {"is_encrypt": 0, "obfuscated_name": "version"},
    "vpw": {"cipher": "DES", "is_encrypt": 1, "key": "r9924ab5", "obfuscated_name": "ca"},
}

DES_TARGET = {
    "protocol": 102,
    "organization": "UWXspnCCJN4sfYlNfqps",
    "appId": "default",
    "os": "web",
    "version": "3.0.0",
    "sdkver": "3.0.0",
    "box": "",
    "rtype": "all",
    "subVersion": "1.0.0",
    "time": 0,
}

BROWSER_ENV = {
    "plugins": "MicrosoftEdgePDFPluginPortableDocumentFormatinternal-pdf-viewer1,MicrosoftEdgePDFViewermhjfbmdgcfjbbpaeojofohoefgiehjai1",
    "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "canvas": "259ffe69",
    "timezone": -480,
    "platform": "Win32",
    "url": "https://www.skland.com/",
    "referer": "",
    "res": "1920_1080_24_1.25",
    "clientSize": "0_0_1080_1920_1920_1080_1920_1080",
    "status": "0011",
}

RSA_PUBLIC_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCmxMNr7n8ZeT0tE1R9j/mPixoinPkeM+k4VGIn/s0k7N5rJAfnZ0eMER+QhwFvshzo0LNmeUkpR8uIlU/GEVr8mN28sKmwd2gpygqj0ePnBmOW4v0ZVwbSYK+izkhVFk2V/doLoMbWy6b+UnA8mkjvg0iYWRByfRsK2gdl7llqCwIDAQAB"


@dataclass
class SignInResult:
    success: bool
    game: str
    nickname: str
    channel: str
    awards: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class UserBinding:
    app_code: str
    game_name: str
    nickname: str
    channel_name: str
    uid: str
    game_id: int
    roles: list[dict] = field(default_factory=list)


@dataclass
class Credential:
    token: str
    cred: str


class SklandAPI:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None
        self._did: str | None = None

    @staticmethod
    def is_signed_today(result: SignInResult) -> bool:
        if result.success:
            return True
        error = result.error.lower() if result.error else ""
        return any(keyword in error for keyword in ["已签到", "请勿重复", "重复签到", "already", "签到过", "今日已"])

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        json_data: dict | None = None,
    ) -> dict:
        client = await self._get_client()
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers)
                else:
                    response = await client.post(url, headers=headers, json=json_data)
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(1)

        raise last_error or Exception(f"Request failed after {self.max_retries} attempts")

    def _des_encrypt(self, key: bytes, data: bytes) -> bytes:
        padding_len = 8 - (len(data) % 8)
        padded_data = data + (b"\x00" * padding_len)
        key_8 = key[:8].ljust(8, b"\x00")

        cipher = DES.new(key_8, DES.MODE_ECB)
        result = b""
        for index in range(0, len(padded_data), 8):
            result += cipher.encrypt(padded_data[index:index + 8])
        return result

    def _apply_des_rules(self, data: dict) -> dict:
        result = {}
        for key, value in data.items():
            str_value = str(value) if not isinstance(value, str) else value
            rule = DES_RULE.get(key)

            if rule:
                if rule.get("is_encrypt") == 1:
                    des_key = rule["key"].encode("utf-8")
                    encrypted = self._des_encrypt(des_key, str_value.encode("utf-8"))
                    result[rule["obfuscated_name"]] = base64.b64encode(encrypted).decode()
                else:
                    result[rule["obfuscated_name"]] = value
            else:
                result[key] = value
        return result

    def _get_tn(self, data: dict) -> str:
        result = ""
        for key in sorted(data.keys()):
            value = data[key]
            if isinstance(value, int):
                result += str(value * 10000)
            elif isinstance(value, dict):
                result += self._get_tn(value)
            else:
                result += str(value) if value else ""
        return result

    def _aes_encrypt(self, data: bytes, key: bytes) -> str:
        encoded_b64 = base64.b64encode(data)
        pad_len = 16 - (len(encoded_b64) % 16)
        if pad_len < 16:
            encoded_b64 += b"\x00" * pad_len

        iv = b"0102030405060708"
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(pad(encoded_b64, 16))
        return encrypted.hex()

    def _get_smid(self) -> str:
        time_str = datetime.now().strftime("%Y%m%d%H%M%S")
        uid = str(uuid.uuid4())
        value = f"{time_str}{hashlib.md5(uid.encode()).hexdigest()}00"
        smsk_web = hashlib.md5(f"smsk_web_{value}".encode()).digest()
        suffix = smsk_web[:7].hex()
        return f"{value}{suffix}0"

    async def get_device_id(self) -> str:
        if self._did:
            return self._did

        uid = str(uuid.uuid4())
        pri_id_hash = hashlib.md5(uid.encode()).digest()[:8]
        pri_id_hex = pri_id_hash.hex()

        public_key_der = base64.b64decode(RSA_PUBLIC_KEY)
        rsa_key = RSA.import_key(public_key_der)
        cipher_rsa = PKCS1_v1_5.new(rsa_key)
        encrypted_uid = cipher_rsa.encrypt(uid.encode())
        ep_base64 = base64.b64encode(encrypted_uid).decode()

        in_ms = int(time.time() * 1000)
        browser = dict(BROWSER_ENV)
        browser["vpw"] = str(uuid.uuid4())
        browser["trees"] = str(uuid.uuid4())
        browser["svm"] = in_ms
        browser["pmf"] = in_ms

        des_target = dict(DES_TARGET)
        des_target["smid"] = self._get_smid()
        des_target.update(browser)

        tn_input = self._get_tn(des_target)
        des_target["tn"] = hashlib.md5(tn_input.encode()).hexdigest()

        des_result = self._apply_des_rules(des_target)
        json_str = json.dumps(des_result, separators=(",", ":"))
        compressed = gzip.compress(json_str.encode(), compresslevel=2)
        encrypted = self._aes_encrypt(compressed, pri_id_hex.encode())

        response = await self._request(
            "POST",
            "https://fp-it.portal101.cn/deviceprofile/v4",
            json_data={
                "appId": "default",
                "compress": 2,
                "data": encrypted,
                "encode": 5,
                "ep": ep_base64,
                "organization": "UWXspnCCJN4sfYlNfqps",
                "os": "web",
            },
        )

        if response.get("code") != 1100:
            raise Exception(f"Device ID generation failed: {response}")

        self._did = f"B{response['detail']['deviceId']}"
        return self._did

    def _generate_signature(self, token: str, path: str, body_or_query: str, did: str) -> tuple[str, dict]:
        timestamp = int(time.time())
        header_ca = {
            "platform": "3",
            "timestamp": str(timestamp),
            "dId": did,
            "vName": "1.0.0",
        }
        header_ca_str = json.dumps(header_ca, separators=(",", ":"))

        source = f"{path}{body_or_query}{timestamp}{header_ca_str}"
        hmac_result = hmac.new(token.encode(), source.encode(), hashlib.sha256).hexdigest()
        return hashlib.md5(hmac_result.encode()).hexdigest(), header_ca

    def _get_base_headers(self, did: str) -> dict:
        return {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "Connection": "close",
            "X-Requested-With": "com.hypergryph.skland",
            "dId": did,
        }

    async def get_authorization(self, user_token: str) -> str:
        did = await self.get_device_id()
        headers = self._get_base_headers(did)

        response = await self._request(
            "POST",
            "https://as.hypergryph.com/user/oauth2/v2/grant",
            headers=headers,
            json_data={"appCode": "4ca99fa6b56cc2ba", "token": user_token, "type": 0},
        )

        if response.get("status") != 0:
            raise Exception(f"Authorization failed: {response.get('message', 'Unknown error')}")

        return response["data"]["code"]

    async def get_credential(self, authorization: str) -> Credential:
        did = await self.get_device_id()
        headers = self._get_base_headers(did)

        response = await self._request(
            "POST",
            "https://zonai.skland.com/web/v1/user/auth/generate_cred_by_code",
            headers=headers,
            json_data={"code": authorization, "kind": 1},
        )

        if response.get("code") != 0:
            raise Exception(f"Credential failed: {response.get('message', 'Unknown error')}")

        data = response["data"]
        return Credential(token=data["token"], cred=data["cred"])

    def _get_signed_headers(
        self,
        url: str,
        method: str,
        body: str | None,
        cred: Credential,
        did: str,
    ) -> dict:
        parsed = urlparse(url)
        path = parsed.path
        query = parsed.query or ""

        if method.upper() == "GET":
            sign, header_ca = self._generate_signature(cred.token, path, query, did)
        else:
            sign, header_ca = self._generate_signature(cred.token, path, body or "", did)

        headers = self._get_base_headers(did)
        headers["cred"] = cred.cred
        headers["sign"] = sign
        headers.update({key: str(value) for key, value in header_ca.items()})
        return headers

    async def get_binding_list(self, cred: Credential) -> list[UserBinding]:
        did = await self.get_device_id()
        url = "https://zonai.skland.com/api/v1/game/player/binding"
        headers = self._get_signed_headers(url, "GET", None, cred, did)
        response = await self._request("GET", url, headers=headers)

        if response.get("code") != 0:
            message = response.get("message", "Unknown error")
            if message == "用户未登录":
                raise Exception("用户登录已过期，请重新绑定")
            raise Exception(f"获取绑定列表失败: {message}")

        bindings = []
        for item in response.get("data", {}).get("list", []):
            app_code = item.get("appCode", "")
            if app_code != "endfield":
                continue

            for binding in item.get("bindingList", []):
                bindings.append(
                    UserBinding(
                        app_code=app_code,
                        game_name=binding.get("gameName", "Unknown"),
                        nickname=binding.get("nickName", "Unknown"),
                        channel_name=binding.get("channelName", "Unknown"),
                        uid=binding.get("uid", ""),
                        game_id=binding.get("gameId", 1),
                        roles=binding.get("roles", []),
                    )
                )
        return bindings

    @staticmethod
    def extract_roles(bindings: list[UserBinding]) -> list[dict]:
        roles = []
        seen = set()
        for binding in bindings:
            for role in binding.roles:
                role_info = {
                    "nickname": role.get("nickname", binding.nickname),
                    "role_id": str(role.get("roleId", "")),
                    "server_id": str(role.get("serverId", "")),
                    "channel_name": binding.channel_name,
                }
                key = (role_info["role_id"], role_info["server_id"], role_info["nickname"])
                if key in seen:
                    continue
                seen.add(key)
                roles.append(role_info)
        return roles

    async def sign_endfield(self, cred: Credential, binding: UserBinding) -> list[SignInResult]:
        results = []
        if not binding.roles:
            return [
                SignInResult(
                    success=False,
                    game="终末地",
                    nickname=binding.nickname,
                    channel=binding.channel_name,
                    error="没有角色数据",
                )
            ]

        did = await self.get_device_id()
        url = "https://zonai.skland.com/web/v1/game/endfield/attendance"

        for role in binding.roles:
            role_nickname = role.get("nickname", binding.nickname)
            role_id = role.get("roleId", "")
            server_id = role.get("serverId", "")

            headers = self._get_signed_headers(url, "POST", "", cred, did)
            headers["Content-Type"] = "application/json"
            headers["sk-game-role"] = f"3_{role_id}_{server_id}"
            headers["referer"] = "https://game.skland.com/"
            headers["origin"] = "https://game.skland.com/"

            client = await self._get_client()
            last_error = None
            response = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = (await client.post(url, headers=headers)).json()
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        await asyncio.sleep(1)
            if response is None:
                raise last_error or Exception("Endfield sign-in request failed")
            logger.info(f"[终末地] {role_nickname} sign-in response: {json.dumps(response, ensure_ascii=False)}")

            if response.get("code") != 0:
                results.append(
                    SignInResult(
                        success=False,
                        game="终末地",
                        nickname=role_nickname,
                        channel=binding.channel_name,
                        error=response.get("message", "Unknown error"),
                    )
                )
                continue

            awards = []
            award_ids = response.get("data", {}).get("awardIds", [])
            resource_map = response.get("data", {}).get("resourceInfoMap", {})
            for award in award_ids:
                award_id = award.get("id", "")
                if award_id in resource_map:
                    info = resource_map[award_id]
                    awards.append(f"{info.get('name', 'Unknown')}x{info.get('count', 1)}")

            results.append(
                SignInResult(
                    success=True,
                    game="终末地",
                    nickname=role_nickname,
                    channel=binding.channel_name,
                    awards=awards,
                )
            )

        return results

    async def get_endfield_profile(self, user_token: str) -> tuple[str, list[dict]]:
        auth_code = await self.get_authorization(user_token)
        cred = await self.get_credential(auth_code)
        bindings = await self.get_binding_list(cred)
        if not bindings:
            return "", []
        nickname = bindings[0].nickname if bindings else ""
        roles = self.extract_roles(bindings)
        return nickname, roles

    async def do_full_sign_in(self, user_token: str) -> tuple[list[SignInResult], str, list[dict]]:
        auth_code = await self.get_authorization(user_token)
        cred = await self.get_credential(auth_code)
        bindings = await self.get_binding_list(cred)

        if not bindings:
            return [], "", []

        nickname = bindings[0].nickname if bindings else ""
        roles = self.extract_roles(bindings)
        results = []
        for binding in bindings:
            results.extend(await self.sign_endfield(cred, binding))
        return results, nickname, roles
