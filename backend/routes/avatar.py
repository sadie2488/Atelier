"""Avatar lane: /api/avatar/* and /api/render/*.

A1-A6: capture + pose validation, wireframe rig, avatar assembly, placement, local compositing,
and the two-stage render endpoint. A7: POST /render returns the local composite immediately and,
when generation is possible, status `pending` while a background worker
(backend/avatar/background.py) attempts the Gemini try-on and verification off this thread; when
it is not possible (no key, or an avatar with no stored source photo), status is `failed` right
away -- A7 is fully severable (A-R6).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from backend.db import get_db
from contract.enums import ErrorCode
from contract.schemas import Avatar, AvatarScanResponse, RenderJob, RenderRequest

from backend.avatar import background, ids, prewarm, service
from backend.avatar.errors import AvatarError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["avatar"])

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.invalid_request: 400,
    ErrorCode.unsupported_image: 415,
    ErrorCode.no_person_detected: 422,
    ErrorCode.pose_rejected: 422,
    ErrorCode.not_found: 404,
    ErrorCode.internal_error: 500,
}


def _error(code: ErrorCode, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=_STATUS_BY_CODE.get(code, 500),
        content={"error": {"code": code.value, "message": message}},
    )


def _clean(doc: dict, model) -> dict:
    """Strip `_id` and any DB-only field (e.g. rig, canvas_w/h) before validating."""
    return {k: v for k, v in doc.items() if k in model.model_fields}


@router.post("/avatar/scan")
async def scan(image: UploadFile = File(...), db=Depends(get_db)):
    data = await image.read()
    try:
        doc = await run_in_threadpool(service.scan, data, db["avatars"])  # CPU-bound; don't block the loop
    except AvatarError as e:
        return _error(e.code, e.message)
    except Exception:  # A9: never an unhandled exception / bare 500
        logger.exception("avatar: scan failed unexpectedly")
        return _error(ErrorCode.internal_error, "Could not process the photo.")
    db["avatars"].insert_one(doc)
    prewarm.schedule(doc, db)  # background; never delays or fails the scan
    return AvatarScanResponse.model_validate(_clean(doc, AvatarScanResponse))


@router.get("/avatar/{avatar_id}")
def get_avatar(avatar_id: str, db=Depends(get_db)):
    doc = db["avatars"].find_one({"avatar_id": avatar_id})
    if doc is None:
        return _error(ErrorCode.not_found, f"No avatar with id {avatar_id!r}.")
    return Avatar.model_validate(_clean(doc, Avatar))


def _promote_queued(cached: dict, body: RenderRequest, avatar_doc: dict, db) -> None:
    """A render still queued in the prewarm executor (pending, not yet claimed) is also submitted to
    the user executor, so the user's click never waits behind other prewarm jobs. background._claim
    guarantees only one of the two actually runs. Best-effort: never fails the request."""
    try:
        top_doc = db["items"].find_one({"id": body.top_id})
        bottom_doc = db["items"].find_one({"id": body.bottom_id})
        jacket_doc = db["items"].find_one({"id": body.jacket_id}) if body.jacket_id is not None else None
        if top_doc is None or bottom_doc is None or (body.jacket_id is not None and jacket_doc is None):
            return
        background.submit(cached["render_id"], avatar_doc, top_doc, bottom_doc, jacket_doc, db["renders"],
                          prewarm=False, attempt=cached.get("attempt"))
    except Exception:
        logger.exception("avatar: could not promote queued render %s", cached.get("render_id"))


@router.post("/render")
def render(body: RenderRequest, db=Depends(get_db)):
    avatar_doc = db["avatars"].find_one({"avatar_id": body.avatar_id})
    if avatar_doc is None:
        return _error(ErrorCode.not_found, f"No avatar with id {body.avatar_id!r}.")

    render_id = ids.render_id_for(body.avatar_id, body.top_id, body.bottom_id, body.jacket_id)
    cached = db["renders"].find_one({"render_id": render_id})
    if cached is not None:
        cached = service.settle_if_stale(cached, db["renders"])
        if cached.get("status") != "failed":
            if cached.get("status") == "pending" and cached.get("claimed") is False:
                _promote_queued(cached, body, avatar_doc, db)
            return RenderJob.model_validate(_clean(cached, RenderJob))
        # A failed try-on is retried when the user asks again, not cached forever.
        db["renders"].delete_one({"render_id": render_id})

    top_doc = db["items"].find_one({"id": body.top_id})
    if top_doc is None:
        return _error(ErrorCode.not_found, f"Item {body.top_id!r} does not exist.")
    bottom_doc = db["items"].find_one({"id": body.bottom_id})
    if bottom_doc is None:
        return _error(ErrorCode.not_found, f"Item {body.bottom_id!r} does not exist.")
    jacket_doc: Optional[dict] = None
    if body.jacket_id is not None:
        jacket_doc = db["items"].find_one({"id": body.jacket_id})
        if jacket_doc is None:
            return _error(ErrorCode.not_found, f"Item {body.jacket_id!r} does not exist.")

    try:
        job = service.render(render_id, avatar_doc, top_doc, bottom_doc, jacket_doc, db["renders"])
    except AvatarError as e:
        return _error(e.code, e.message)
    except Exception:  # A9: never an unhandled exception / bare 500
        logger.exception("avatar: render failed unexpectedly")
        return _error(ErrorCode.internal_error, "Could not build the render.")

    return RenderJob.model_validate(_clean(job, RenderJob))


@router.get("/render/{render_id}")
def get_render(render_id: str, db=Depends(get_db)):
    doc = db["renders"].find_one({"render_id": render_id})
    if doc is None:
        return _error(ErrorCode.not_found, f"No render with id {render_id!r}.")
    doc = service.settle_if_stale(doc, db["renders"])
    return RenderJob.model_validate(_clean(doc, RenderJob))


# ---------------------------------------------------------------- phone upload page (demo aux)
# Auxiliary demo routes outside the frozen JSON API: the phone only takes and uploads the photo;
# the app itself runs on the laptop. Relative URLs throughout so it works behind the Vercel proxy.

_PHONE_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atelier scan</title>
<style>
body{margin:0;font-family:-apple-system,system-ui,sans-serif;background:#faf8f5;color:#222;}
main{max-width:480px;margin:0 auto;padding:24px 16px;text-align:center;}
h1{font-size:1.6rem;margin:8px 0 12px;}
p{line-height:1.4;}
.consent{font-size:.85rem;color:#666;}
.btn{display:block;width:100%;box-sizing:border-box;padding:18px;font-size:1.2rem;border:0;border-radius:12px;
background:#222;color:#fff;margin:16px 0;cursor:pointer;}
input[type=file]{display:none;}
.spinner{width:40px;height:40px;margin:16px auto;border:4px solid #ddd;border-top-color:#222;border-radius:50%;
animation:spin 1s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
ul{text-align:left;}
img{max-width:100%;max-height:60vh;margin-top:12px;}
.hidden{display:none;}
</style></head>
<body><main>
<h1>Atelier scan</h1>
<p class="consent">Your photo is sent to Google's Gemini API to create your try-on.</p>
<div id="start">
<p>Full body head to feet, arms slightly away from your body, face the light.</p>
<form id="form"><label class="btn" for="image">Take photo</label>
<input id="image" name="image" type="file" accept="image/*" capture="environment"></form>
</div>
<div id="busy" class="hidden"><div class="spinner"></div><p>Checking your pose…</p></div>
<div id="done" class="hidden"><p><strong>Done — continue on the laptop.</strong></p><img id="avatar" alt="Your avatar"></div>
<div id="rejected" class="hidden"><ul id="reasons"></ul><button class="btn" id="retake" type="button">Retake</button></div>
</main>
<script>
(function(){
var $=function(id){return document.getElementById(id);};
function show(id){["start","busy","done","rejected"].forEach(function(k){$(k).classList.toggle("hidden",k!==id);});}
function reject(msg){
  var ul=$("reasons");ul.innerHTML="";
  String(msg||"Could not process the photo.").split("\\n").forEach(function(line){
    if(line.trim()){var li=document.createElement("li");li.textContent=line.trim();ul.appendChild(li);}
  });
  show("rejected");
}
function downscale(file){
  return new Promise(function(resolve){
    var url=URL.createObjectURL(file);var img=new Image();
    img.onload=function(){
      var s=Math.min(1,1600/Math.max(img.naturalWidth,img.naturalHeight));
      var c=document.createElement("canvas");c.width=Math.round(img.naturalWidth*s);c.height=Math.round(img.naturalHeight*s);
      c.getContext("2d").drawImage(img,0,0,c.width,c.height);URL.revokeObjectURL(url);
      c.toBlob(function(b){resolve(b||file);},"image/jpeg",0.9);
    };
    img.onerror=function(){URL.revokeObjectURL(url);resolve(file);};
    img.src=url;
  });
}
$("image").addEventListener("change",function(){
  var f=this.files&&this.files[0];if(!f)return;show("busy");
  downscale(f).then(function(blob){
    var fd=new FormData();fd.append("image",blob,"scan.jpg");
    return fetch("/api/avatar/scan",{method:"POST",body:fd});
  }).then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
  .then(function(res){
    if(res.ok&&res.j.avatar_url){$("avatar").src=res.j.avatar_url;show("done");}
    else{reject(res.j&&res.j.error&&res.j.error.message);}
  }).catch(function(){reject("Upload failed — check the connection and try again.");});
});
$("retake").addEventListener("click",function(){$("image").value="";show("start");});
})();
</script>
</body></html>
"""


@router.get("/phone", response_class=HTMLResponse, include_in_schema=False)
def phone_page():
    return HTMLResponse(_PHONE_HTML)


@router.get("/phone/latest", include_in_schema=False)
def phone_latest(db=Depends(get_db)):
    docs = list(db["avatars"].find({}).sort("created_at", -1).limit(1))
    if not docs:
        return _error(ErrorCode.not_found, "No avatar has been scanned yet.")
    return RedirectResponse(f"/scan?backup={docs[0]['avatar_id']}", status_code=302)
