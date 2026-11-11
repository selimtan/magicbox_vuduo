# magicbox_vuduo

Magic Box OS 2.0.0 R9, **orijinal Vu+ Duo** için OpenPLi 9.2 tabanlı bir imajdır. Magic Box ana ekranı Enigma2'nin C++/Python kaynaklarına gömülüdür; sonradan açılan bir launcher eklentisi değildir.

## Özellikler

- TV, IPTV, Medya, Favorites ve Settings sekmeleri.
- Uydu kanal listeleri, buket/kategori gezinmesi ve Türksat TKGS istemcisi.
- Xtream uyumlu IPTV hesabı, kategori önbelleği ve 500 ms seçim beklemesinden sonra iptal edilebilir ön izleme.
- TV/IPTV ortak favorileri; sarı tuşla ekleme/çıkarma ve satır sonunda yıldız.
- Medya sekmesinde dosya/klasör listesi ve EMC oynatıcısı.
- Tam ekran IPTV'de sağ/sol kanal değiştirme; yukarı/aşağı ile listeye dönüş.
- Sekiz satırlık sayfalama, eğik sekmeler, kenar yumuşatma ve altta yeşil Sony tarzı ses göstergesi.
- Tam ekran kanal değişiminde görüntünün üzerinde alt bilgi şeridi.
- Yalnız Türkçe ve İngilizce arayüz/dil paketleri.
- Katmanda tanımlanan Magic Box güncelleme depoları ve güven sertifikası.

## Kaynak düzeni

| Dizin | İçerik |
| --- | --- |
| `enigma2/` | R9 yamaları uygulanmış, okunabilir Enigma2 kaynakları. Yerleşik arayüz: `lib/gui/emagicbox*`, `lib/magicbox/` ve `lib/python/Screens/MagicBox*`. |
| `EnhancedMovieCenter/` | OpenPLi uyumluluk yaması uygulanmış EMC kaynakları. |
| `servicemp3/` | IPTV iptali, video metadata ve yerel dosya atlama düzeltmeleri uygulanmış oynatıcı kaynakları. |
| `meta-magicbox/` | Asıl derleme katmanı: tarifler, yamalar, skin, görseller, bootlogo ve fabrika ayarları. |
| `openpli-oe-core` | Resmî OpenPLi derleme deposuna, doğrulanmış commit'te sabitlenmiş Git alt modülü. |
| `scripts/` | İmaj derleme, biçim/gizlilik denetimi ve tam imaj paketlerinden feed hazırlama araçları. |
| `source-manifest.json` | R9 katman dosyalarının SHA256 özetleri ve upstream/BSP commit'leri. |
| `SOURCE_PROVENANCE.json` | Kaynak snapshotlarının upstream ve yama bilgileri. |
| `releases/R9.json` | Son yerel imajın sürüm, SHA256 ve doğrulama özeti. |

Derleme tarifleri resmî kaynakları sabit commit'te alır ve `meta-magicbox` yamalarını uygular. Buradaki üç okunabilir kaynak ağacı, aynı yamalar uygulanmış snapshotlardır. Bu ağaçlarda geliştirme yapıldığında ilgili katman yaması ve `source-manifest.json` da güncellenmelidir.

## Derleme

Desteklenen ortam Ubuntu 20.04 Linux'tur. Normal bir kullanıcıyla çalıştırın; ilk hazırlık `sudo` ile bağımlılıkları kurar ve gerekirse 8 GiB swap hazırlar. Derleme indirmeleri/çalışma alanı için yeterli disk ve bellek ayırın.

```sh
git clone https://github.com/selimtan/magicbox_vuduo.git "$HOME/magicbox-source"
cd "$HOME/magicbox-source"
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \
  MAGICBOX_BUILD_TARGET=magicbox-image MAGICBOX_BUILD_JOBS=4 \
  bash scripts/vm-setup-build.sh
```

Bağımlılıklar ve `en_US.UTF-8` yerel ayarı önceden hazırsa `MAGICBOX_DEPS_READY=1` eklenebilir. Yardımcı betik resmî OpenPLi deposunu `$HOME/openpli-oe-core` altında hazırlar, BSP'leri sabit sürümlerde alır ve `MACHINE=vuduo` ile `magicbox-image` hedefini derler. Daha küçük makinelerde `MAGICBOX_BUILD_JOBS=2` kullanılabilir.

Çıktı: `$HOME/openpli-oe-core/build/tmp/deploy/images/vuduo/magicbox-2.0.0-vuduo_usb.zip`.

OpenPLi derleme metadata'sını bu depo içinde incelemek için isteğe bağlı olarak:

```sh
git submodule update --init openpli-oe-core
```

Derleme yardımcısı kendi OpenPLi checkout'unu hazırladığından bu son komut imaj üretimi için zorunlu değildir. Diğer paketlerin kaynakları sabit upstream tariflerinden derleme sırasında alınır; bu depo bütün Linux dağıtım kaynaklarının tek bir vendored kopyası değildir.

## R9 doğrulaması

R9, yerel bilgisayardaki Linux ortamında derlendi; 6.808 görev başarılı oldu. Değişen 48 Enigma2 kaynak dosyası, 126 görsel dosyası, MIPS32/o32 hard float ikilileri ve imajın tam 589 paketi kontrol edildi. ZIP'in UBI/UBIFS ve çekirdek biçimi, dil sınırı ve bilinen kişisel IPTV bilgilerinin yokluğu doğrulandı.

Bu Git deposu kaynak kodunu içerir; flashlanabilir ZIP, IPK deposu, sanal makine diskleri veya cihaz yedekleri içermez. R9 ZIP'inin bu kayıt hazırlanırken alıcıda açılış testi yapılmamıştır. Bütün ekranların 500 ms hedefini sağladığı veya fiziksel TKGS yayınının uçtan uca doğrulandığı iddia edilmez.

## Özel veriler ve lisanslar

Kişisel IPTV sunucusu/kullanıcı adı/parola, favoriler, NAS bağlantısı, SSH anahtarları ve sunucu yönetim bilgileri bu depoya dahil değildir. Kullanıcının hesabı cihazda girilir ve cihazda saklanır. Genel güncelleme adresi ve kamuya açık güven sertifikası imajın gerekli derleme girdileridir; kendi sunucunuzla kullanacaksanız bunları katmanda değiştirin.

Her upstream bileşenin lisansı ve telif bildirimleri korunmuştur; ayrıntılar için [LICENSE.md](LICENSE.md) dosyasına bakın.
