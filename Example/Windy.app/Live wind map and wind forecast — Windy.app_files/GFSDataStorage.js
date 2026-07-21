/**
 * Created by mrbond on 06/08/16.
 */
class GFSDataStorage {
    constructor(data) {
        this.dx = data.config.dx;
        this.dy = data.config.dy;
        this.lat1 = data.config.lat1;
        this.lat2 = data.config.lat2;
        this.lon1 = data.config.lon1;
        this.lon2 = data.config.lon2;
        this.longitudeCount = (this.lon2 - this.lon1) / this.dx + 1;
        this.data = data.data;
    }
    rawValueFor(lat, lon) {
        if (lon < this.lon1) {
            lon += 360.0;
        }
        if (lon > this.lon2) {
            lon -= 360.0;
        }
        let latIdx = Math.floor((lat - this.lat1) / this.dy);
        let lonIdx = Math.floor((lon - this.lon1) / this.dx);
        let idx = (latIdx * this.longitudeCount + lonIdx);
        let val = 0;
        if (idx >= this.data.length || idx < 0) {
            console.log("failed to get uv value: ", lat, "x", lon, " idx: ", idx, " length:", this.data.length);
            val = this.data[0];
        }
        else {
            val = this.data[idx];
        }
        return val;
    }
    static getAvg(lon, lat, lon1, lat1, lon2, lat2, v1, v2, v3, v4) {
        let xd = (lon - lon1) / (lon2 - lon1);
        let top = (v2 - v1) * xd + v1;
        let bottom = (v4 - v3) * xd + v3;
        return (bottom - top) * (lat - lat1) / (lat2 - lat1) + top;
    }
    valueFor(lat, lon) {
        let lat1 = Math.floor(lat / this.dy) * this.dy;
        let lat2 = Math.ceil(lat / this.dy) * this.dy;
        let lon1 = Math.floor(lon / this.dx) * this.dx;
        let lon2 = Math.ceil(lon / this.dx) * this.dx;
        let result = 0.0;
        if (lat1 == lat2 && lon1 == lon2) {
            result = this.rawValueFor(lat1, lon1);
        }
        else if (lat1 == lat2) {
            let val1 = this.rawValueFor(lat, lon1);
            let val2 = this.rawValueFor(lat, lon2);
            let val = (val2 - val1) * (lon - lon1) / (lon2 - lon1) + val1;
            result = val;
        }
        else if (lon1 == lon2) {
            let val1 = this.rawValueFor(lat1, lon);
            let val2 = this.rawValueFor(lat2, lon);
            let val = (val2 - val1) * (lat - lat1) / (lat2 - lat1) + val1;
            result = val;
        }
        else {
            let val1 = this.rawValueFor(lat1, lon1);
            let val2 = this.rawValueFor(lat1, lon2);
            let val3 = this.rawValueFor(lat2, lon1);
            let val4 = this.rawValueFor(lat2, lon2);
            result = GFSDataStorage.getAvg(lon, lat, lon1, lat1, lon2, lat2, val1, val2, val3, val4);
            ;
        }
        return result;
    }
}
