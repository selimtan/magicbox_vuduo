/* Cancellable worker transfer; SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef ENIGMA_MAGICBOX_CURLTRANSFER_H
#define ENIGMA_MAGICBOX_CURLTRANSFER_H
#include <atomic>
#include <chrono>
#include <thread>
#include <curl/curl.h>

namespace MagicBox {
inline CURLcode performCancellable(CURL* easy, const std::atomic<bool>& stopped) {
	if(stopped)return CURLE_ABORTED_BY_CALLBACK;
	CURLM* multi=curl_multi_init();
	if(!multi)return CURLE_FAILED_INIT;
	if(curl_multi_add_handle(multi,easy)!=CURLM_OK) { curl_multi_cleanup(multi);return CURLE_FAILED_INIT; }
	CURLcode result=CURLE_FAILED_INIT;
	while(true) {
		if(stopped) { result=CURLE_ABORTED_BY_CALLBACK;break; }
		int running=0;
		if(curl_multi_perform(multi,&running)!=CURLM_OK) { result=CURLE_RECV_ERROR;break; }
		int remaining=0;bool finished=false;
		while(auto message=curl_multi_info_read(multi,&remaining)) {
			if(message->msg==CURLMSG_DONE && message->easy_handle==easy) { result=message->data.result;finished=true;break; }
		}
		if(finished || !running)break;
		int ready=0;
		if(curl_multi_wait(multi,nullptr,0,25,&ready)!=CURLM_OK) { result=CURLE_RECV_ERROR;break; }
		// curl_multi_wait may return immediately when there are no descriptors.
		if(!ready && !stopped)std::this_thread::sleep_for(std::chrono::milliseconds(25));
	}
	curl_multi_remove_handle(multi,easy);
	curl_multi_cleanup(multi);
	return result;
}
}
#endif
