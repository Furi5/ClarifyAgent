import requests

url = "https://www.i-mak.org/wp-content/uploads/2021/05/i-mak.keytruda.report-2021-05-06F.pdf"
headers = {
    "Authorization": "Bearer jina_1645a67fefca4a4ea45e05c38006dec4HqFpr0YfCcCmVIv3t5hwlvUwdRYL"
}

response = requests.get(url, headers=headers)
print(response.text)
